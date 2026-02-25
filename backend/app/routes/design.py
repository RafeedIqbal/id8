from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies.idempotency import get_idempotency_key
from app.models.enums import ArtifactType, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.schemas.artifact import ArtifactResponse, ProjectArtifactResponse
from app.schemas.design import DesignFeedbackRequest, DesignGenerateRequest

router = APIRouter(tags=["design"])

_DESIGN_VALID_STATUSES = {ProjectStatus.PRD_APPROVED, ProjectStatus.DESIGN_DRAFT}


async def _latest_run(db: AsyncSession, project_id: uuid.UUID) -> ProjectRun:
    result = await db.execute(
        select(ProjectRun)
        .where(ProjectRun.project_id == project_id)
        .order_by(ProjectRun.created_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=409, detail="No active run for this project")
    return run


async def _next_design_version(db: AsyncSession, project_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(ProjectArtifact.version), 0)).where(
            ProjectArtifact.project_id == project_id,
            ProjectArtifact.artifact_type == ArtifactType.DESIGN_SPEC,
        )
    )
    return (result.scalar() or 0) + 1


@router.post(
    "/projects/{projectId}/design/generate",
    operation_id="generateDesign",
    response_model=ArtifactResponse,
    status_code=202,
)
async def generate_design(
    body: DesignGenerateRequest,
    project_id: uuid.UUID = Path(alias="projectId"),
    idempotency_key: str | None = Depends(get_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status not in _DESIGN_VALID_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot generate design in status {project.status}")

    run = await _latest_run(db, project_id)
    version = await _next_design_version(db, project_id)

    artifact = ProjectArtifact(
        project_id=project_id,
        run_id=run.id,
        artifact_type=ArtifactType.DESIGN_SPEC,
        version=version,
        model_profile=body.model_profile,
        content={"status": "pending", "provider": body.provider.value},
    )
    db.add(artifact)

    # Transition to design_draft if not already
    if project.status != ProjectStatus.DESIGN_DRAFT:
        project.status = ProjectStatus.DESIGN_DRAFT

    await db.commit()
    await db.refresh(artifact)

    # TODO: enqueue design generation job via orchestrator
    return {"artifact": ProjectArtifactResponse.model_validate(artifact)}


@router.post(
    "/projects/{projectId}/design/feedback",
    operation_id="submitDesignFeedback",
    response_model=ArtifactResponse,
    status_code=202,
)
async def submit_design_feedback(
    body: DesignFeedbackRequest,
    project_id: uuid.UUID = Path(alias="projectId"),
    idempotency_key: str | None = Depends(get_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != ProjectStatus.DESIGN_DRAFT:
        raise HTTPException(status_code=409, detail="Design feedback only accepted in design_draft status")

    run = await _latest_run(db, project_id)
    version = await _next_design_version(db, project_id)

    artifact = ProjectArtifact(
        project_id=project_id,
        run_id=run.id,
        artifact_type=ArtifactType.DESIGN_SPEC,
        version=version,
        content={
            "status": "pending",
            "feedback": body.feedback_text,
            "target_screen_id": body.target_screen_id,
            "target_component_id": body.target_component_id,
        },
    )
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)

    # TODO: enqueue design regeneration job via orchestrator
    return {"artifact": ProjectArtifactResponse.model_validate(artifact)}
