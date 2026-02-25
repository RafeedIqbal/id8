from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.models.project_run import ProjectRun
from app.schemas.run import CreateRunRequest, ProjectRunResponse

router = APIRouter(tags=["runs"])


@router.post("/projects/{project_id}/runs", response_model=ProjectRunResponse, status_code=202)
async def create_run(
    project_id: uuid.UUID,
    body: CreateRunRequest | None = None,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
) -> ProjectRun:
    # Check project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Idempotency: return existing run if key matches
    if idempotency_key:
        run_result = await db.execute(select(ProjectRun).where(ProjectRun.idempotency_key == idempotency_key))
        existing_run = run_result.scalar_one_or_none()
        if existing_run is not None:
            return existing_run

    start_node = "IngestPrompt"
    if body and body.resume_from_node:
        start_node = body.resume_from_node

    run = ProjectRun(
        project_id=project_id,
        status=ProjectStatus.IDEATION,
        current_node=start_node,
        idempotency_key=idempotency_key,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # TODO: enqueue run for worker/orchestrator processing

    return run
