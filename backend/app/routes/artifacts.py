from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.schemas.artifact import ArtifactListResponse, ProjectArtifactResponse

router = APIRouter(tags=["artifacts"])


@router.get("/projects/{project_id}/artifacts", response_model=ArtifactListResponse)
async def list_artifacts(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(ProjectArtifact)
        .where(ProjectArtifact.project_id == project_id)
        .order_by(ProjectArtifact.artifact_type, ProjectArtifact.version.desc())
    )
    artifacts = result.scalars().all()

    return {"items": [ProjectArtifactResponse.model_validate(a) for a in artifacts]}
