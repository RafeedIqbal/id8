from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.schemas.artifact import ArtifactResponse
from app.schemas.design import DesignFeedbackRequest, DesignGenerateRequest

router = APIRouter(tags=["design"])

_DESIGN_VALID_STATUSES = {ProjectStatus.PRD_APPROVED, ProjectStatus.DESIGN_DRAFT}


@router.post("/projects/{project_id}/design/generate", response_model=ArtifactResponse, status_code=202)
async def generate_design(
    project_id: uuid.UUID,
    body: DesignGenerateRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status not in _DESIGN_VALID_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot generate design in status {project.status}")

    # TODO: queue design generation job via orchestrator
    raise HTTPException(status_code=501, detail="Design generation not yet implemented")


@router.post("/projects/{project_id}/design/feedback", response_model=ArtifactResponse, status_code=202)
async def submit_design_feedback(
    project_id: uuid.UUID,
    body: DesignFeedbackRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != ProjectStatus.DESIGN_DRAFT:
        raise HTTPException(status_code=409, detail="Design feedback only accepted in design_draft status")

    # TODO: queue design regeneration job via orchestrator
    raise HTTPException(status_code=501, detail="Design feedback not yet implemented")
