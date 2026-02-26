from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session, get_db
from app.dependencies.idempotency import get_idempotency_key
from app.models.approval_event import ApprovalEvent
from app.models.deployment_record import DeploymentRecord
from app.models.enums import ApprovalStage, ProjectStatus
from app.models.project import Project
from app.models.project_run import ProjectRun
from app.orchestrator import NodeName, run_orchestrator
from app.schemas.deploy import DeploymentRecordResponse, DeployRequest

router = APIRouter(tags=["deploy"])
logger = logging.getLogger(__name__)


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
    "/projects/{projectId}/deploy",
    operation_id="deployProject",
    response_model=DeploymentRecordResponse,
    status_code=202,
)
async def deploy_project(
    background_tasks: BackgroundTasks,
    project_id: uuid.UUID = Path(alias="projectId"),
    body: DeployRequest | None = None,
    idempotency_key: str | None = Depends(get_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # 1. Verify project exists.
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Verify project is in deploy_ready status.
    if project.status != ProjectStatus.DEPLOY_READY:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot deploy: project status is '{project.status}' (expected 'deploy_ready')",
        )

    # 3. Verify deploy approval exists.
    result = await db.execute(
        select(ApprovalEvent).where(
            ApprovalEvent.project_id == project_id,
            ApprovalEvent.stage == ApprovalStage.DEPLOY,
            ApprovalEvent.decision == "approved",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="A 'deploy' approval event is required before deployment",
        )

    # 4. Find the active run parked at WaitDeployApproval.
    result = await db.execute(
        select(ProjectRun)
        .where(ProjectRun.project_id == project_id)
        .order_by(ProjectRun.created_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=409, detail="No active run for this project")

    if run.current_node != NodeName.WAIT_DEPLOY_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run is at node '{run.current_node}'; deployment can only be "
                f"triggered from '{NodeName.WAIT_DEPLOY_APPROVAL}'"
            ),
        )

    # 5. Create a queued DeploymentRecord (idempotent — skip if already queued).
    result = await db.execute(
        select(DeploymentRecord)
        .where(
            DeploymentRecord.run_id == run.id,
            DeploymentRecord.environment == "production",
            DeploymentRecord.status == "queued",
        )
        .limit(1)
    )
    existing_record = result.scalar_one_or_none()

    if existing_record is None:
        record = DeploymentRecord(
            project_id=project_id,
            run_id=run.id,
            environment="production",
            status="queued",
            provider_payload={},
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
    else:
        record = existing_record

    # 6. Transition project to deploying and persist before triggering background work.
    project.status = ProjectStatus.DEPLOYING
    await db.commit()
    await db.refresh(record)

    # 7. Trigger orchestrator to resume from WaitDeployApproval → DeployProduction.
    background_tasks.add_task(_run_orchestrator_background, run.id)

    return DeploymentRecordResponse.model_validate(record)
