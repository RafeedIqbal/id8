from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies.idempotency import get_idempotency_key
from app.models.approval_event import ApprovalEvent
from app.models.deployment_record import DeploymentRecord
from app.models.enums import ApprovalStage, ProjectStatus
from app.models.project import Project
from app.models.project_run import ProjectRun
from app.schemas.deploy import DeploymentRecordResponse, DeployRequest

router = APIRouter(tags=["deploy"])


@router.post(
    "/projects/{projectId}/deploy",
    operation_id="deployProject",
    response_model=DeploymentRecordResponse,
    status_code=202,
)
async def deploy_project(
    project_id: uuid.UUID = Path(alias="projectId"),
    body: DeployRequest | None = None,
    idempotency_key: str | None = Depends(get_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Verify project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status != ProjectStatus.DEPLOY_READY:
        raise HTTPException(status_code=409, detail=f"Cannot deploy in status {project.status}")

    # Verify deploy approval exists
    result = await db.execute(
        select(ApprovalEvent).where(
            ApprovalEvent.project_id == project_id,
            ApprovalEvent.stage == ApprovalStage.DEPLOY,
            ApprovalEvent.decision == "approved",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Deploy approval required before deployment")

    # Find active run
    result = await db.execute(
        select(ProjectRun)
        .where(ProjectRun.project_id == project_id)
        .order_by(ProjectRun.created_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=409, detail="No active run for this project")

    record = DeploymentRecord(
        project_id=project_id,
        run_id=run.id,
        environment=body.target if body else "production",
        status="queued",
        provider_payload={},
    )
    db.add(record)

    # Transition project status
    project.status = ProjectStatus.DEPLOYING

    await db.commit()
    await db.refresh(record)

    # TODO: trigger deploy via orchestrator
    return DeploymentRecordResponse.model_validate(record)
