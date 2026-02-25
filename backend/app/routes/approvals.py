from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session, get_db
from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage, ProjectStatus
from app.models.project import Project
from app.models.project_run import ProjectRun
from app.orchestrator import NodeName, run_orchestrator
from app.schemas.approval import ApprovalEventResponse, ApprovalRequest

router = APIRouter(tags=["approvals"])
logger = logging.getLogger(__name__)

# Which project status is valid for each approval stage
_STAGE_TO_VALID_STATUS: dict[ApprovalStage, ProjectStatus] = {
    ApprovalStage.PRD: ProjectStatus.PRD_DRAFT,
    ApprovalStage.DESIGN: ProjectStatus.DESIGN_DRAFT,
    ApprovalStage.TECH_PLAN: ProjectStatus.TECH_PLAN_DRAFT,
    ApprovalStage.DEPLOY: ProjectStatus.DEPLOY_READY,
}

# On approval, what status to transition to
_STAGE_TO_APPROVED_STATUS: dict[ApprovalStage, ProjectStatus] = {
    ApprovalStage.PRD: ProjectStatus.PRD_APPROVED,
    ApprovalStage.DESIGN: ProjectStatus.DESIGN_APPROVED,
    ApprovalStage.TECH_PLAN: ProjectStatus.TECH_PLAN_APPROVED,
    ApprovalStage.DEPLOY: ProjectStatus.DEPLOYING,
}
_STAGE_TO_WAIT_NODE: dict[ApprovalStage, NodeName] = {
    ApprovalStage.PRD: NodeName.WAIT_PRD_APPROVAL,
    ApprovalStage.DESIGN: NodeName.WAIT_DESIGN_APPROVAL,
    ApprovalStage.TECH_PLAN: NodeName.WAIT_TECH_PLAN_APPROVAL,
    ApprovalStage.DEPLOY: NodeName.WAIT_DEPLOY_APPROVAL,
}


async def _run_orchestrator_background(run_id: uuid.UUID) -> None:
    """Fire-and-forget wrapper that opens its own DB session."""
    async with async_session() as db:
        try:
            await run_orchestrator(run_id, db)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Background orchestrator run failed for run_id=%s", run_id)


@router.post(
    "/projects/{projectId}/approvals",
    operation_id="submitApproval",
    response_model=ApprovalEventResponse,
)
async def submit_approval(
    body: ApprovalRequest,
    background_tasks: BackgroundTasks,
    project_id: uuid.UUID = Path(alias="projectId"),
    db: AsyncSession = Depends(get_db),
) -> ApprovalEvent:
    # Load project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate stage matches current status
    valid_status = _STAGE_TO_VALID_STATUS.get(body.stage)
    if project.status != valid_status:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit {body.stage} approval when project status is {project.status}",
        )

    # Find active run
    result = await db.execute(
        select(ProjectRun).where(ProjectRun.project_id == project_id).order_by(ProjectRun.created_at.desc()).limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=409, detail="No active run for this project")
    expected_wait_node = _STAGE_TO_WAIT_NODE[body.stage]
    if run.current_node != expected_wait_node:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run is at node {run.current_node}; {body.stage} approvals are only valid at "
                f"{expected_wait_node}"
            ),
        )

    # Create approval event
    # TODO: resolve actor from auth context
    event = ApprovalEvent(
        project_id=project_id,
        run_id=run.id,
        stage=body.stage,
        decision=body.decision,
        notes=body.notes,
        created_by=uuid.UUID("00000000-0000-0000-0000-000000000000"),
    )
    db.add(event)

    # Transition project status
    if body.decision == "approved":
        project.status = _STAGE_TO_APPROVED_STATUS[body.stage]
    # On rejection, status stays at current (generation node will re-run)

    await db.commit()
    await db.refresh(event)

    # Resume the parked orchestrator run
    background_tasks.add_task(_run_orchestrator_background, run.id)

    return event
