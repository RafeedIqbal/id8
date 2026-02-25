from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage, ProjectStatus
from app.models.project import Project
from app.schemas.deploy import DeploymentRecordResponse, DeployRequest

router = APIRouter(tags=["deploy"])


@router.post("/projects/{project_id}/deploy", response_model=DeploymentRecordResponse, status_code=202)
async def deploy_project(
    project_id: uuid.UUID,
    body: DeployRequest | None = None,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
) -> dict:
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

    # TODO: trigger deploy via orchestrator
    raise HTTPException(status_code=501, detail="Deployment not yet implemented")
