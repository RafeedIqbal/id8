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
from app.models.enums import ApprovalStage, ArtifactType, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.observability import emit_audit_event
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
) -> DeploymentRecordResponse:
    # 1. Verify project exists.
    project_result = await db.execute(select(Project).where(Project.id == project_id, Project.deleted_at.is_(None)))
    project = project_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    requested_target = body.target if body is not None else "production"
    if requested_target != "production":
        raise HTTPException(status_code=422, detail="Only target='production' is supported")

    selected_artifact_id: str | None = None
    if body is not None and body.artifact_id is not None:
        artifact_result = await db.execute(
            select(ProjectArtifact).where(
                ProjectArtifact.id == body.artifact_id,
                ProjectArtifact.project_id == project_id,
                ProjectArtifact.artifact_type == ArtifactType.CODE_SNAPSHOT,
            )
        )
        artifact = artifact_result.scalar_one_or_none()
        if artifact is None:
            raise HTTPException(
                status_code=422,
                detail="artifact_id is not a valid code_snapshot artifact for this project",
            )
        selected_artifact_id = str(artifact.id)

    if idempotency_key:
        key_result = await db.execute(
            select(DeploymentRecord)
            .where(DeploymentRecord.provider_payload["idempotency_key"].astext == idempotency_key)
            .order_by(DeploymentRecord.created_at.desc())
            .limit(1)
        )
        existing_key_record = key_result.scalar_one_or_none()
        if existing_key_record is not None:
            if existing_key_record.project_id != project_id:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key already used for a different project",
                )
            return DeploymentRecordResponse.model_validate(existing_key_record)

    # 2. Verify project is in deploy_ready status.
    if project.status != ProjectStatus.DEPLOY_READY:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot deploy: project status is '{project.status}' (expected 'deploy_ready')",
        )

    # 3. Verify deploy approval exists.
    approval_result = await db.execute(
        select(ApprovalEvent).where(
            ApprovalEvent.project_id == project_id,
            ApprovalEvent.stage == ApprovalStage.DEPLOY,
            ApprovalEvent.decision == "approved",
        )
    )
    if not approval_result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="A 'deploy' approval event is required before deployment",
        )

    # 4. Find the active run parked at WaitDeployApproval.
    run_result = await db.execute(
        select(ProjectRun)
        .where(ProjectRun.project_id == project_id)
        .order_by(ProjectRun.created_at.desc(), ProjectRun.id.desc())
        .limit(1)
    )
    run = run_result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=409, detail="No active run for this project")

    if run.current_node == NodeName.END_SUCCESS:
        raise HTTPException(
            status_code=409,
            detail=(f"Run is at terminal node '{NodeName.END_SUCCESS}'; deployment is already complete"),
        )

    # 5. Create a queued DeploymentRecord (idempotent — skip if already queued).
    record_result = await db.execute(
        select(DeploymentRecord)
        .where(
            DeploymentRecord.run_id == run.id,
            DeploymentRecord.environment == "production",
            DeploymentRecord.status == "queued",
        )
        .limit(1)
    )
    existing_record = record_result.scalar_one_or_none()

    if existing_record is None:
        provider_payload: dict[str, Any] = {"requested_target": requested_target}
        if selected_artifact_id is not None:
            provider_payload["artifact_id"] = selected_artifact_id
        if idempotency_key:
            provider_payload["idempotency_key"] = idempotency_key

        record = DeploymentRecord(
            project_id=project_id,
            run_id=run.id,
            environment="production",
            status="queued",
            provider_payload=provider_payload,
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
    else:
        record = existing_record

    # 6. Force the run back to the deploy wait gate so orchestrator will
    # deterministically process the recorded deploy-approval event.
    previous_node = run.current_node
    run.current_node = NodeName.WAIT_DEPLOY_APPROVAL
    run.status = ProjectStatus.DEPLOY_READY
    await emit_audit_event(
        project_id,
        None,
        "orchestrator.run_requeued",
        {
            "run_id": str(run.id),
            "from_node": str(previous_node),
            "to_node": str(NodeName.WAIT_DEPLOY_APPROVAL),
            "outcome": "requeued_for_deploy",
        },
        db,
    )

    # 7. Transition project to deploying and persist before triggering background work.
    project.status = ProjectStatus.DEPLOYING
    await db.commit()
    await db.refresh(record)

    # 8. Trigger orchestrator to resume from WaitDeployApproval → DeployProduction.
    background_tasks.add_task(_run_orchestrator_background, run.id)

    return DeploymentRecordResponse.model_validate(record)
