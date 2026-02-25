from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session, get_db
from app.dependencies.idempotency import get_idempotency_key
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.models.project_run import ProjectRun
from app.orchestrator import ALL_NODE_NAMES, run_orchestrator
from app.schemas.run import CreateRunRequest, ProjectRunResponse

router = APIRouter(tags=["runs"])


async def _run_orchestrator_background(run_id: uuid.UUID) -> None:
    """Fire-and-forget wrapper that opens its own DB session."""
    async with async_session() as db:
        await run_orchestrator(run_id, db)
        await db.commit()


@router.post("/projects/{projectId}/runs", operation_id="createRun", response_model=ProjectRunResponse, status_code=202)
async def create_run(
    background_tasks: BackgroundTasks,
    project_id: uuid.UUID = Path(alias="projectId"),
    body: CreateRunRequest | None = None,
    idempotency_key: str | None = Depends(get_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> ProjectRun:
    # Check project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Idempotency: return existing run if key matches
    if idempotency_key:
        run_result = await db.execute(
            select(ProjectRun).where(
                ProjectRun.project_id == project_id,
                ProjectRun.idempotency_key == idempotency_key,
            )
        )
        existing_run = run_result.scalar_one_or_none()
        if existing_run is not None:
            return existing_run

        key_result = await db.execute(select(ProjectRun).where(ProjectRun.idempotency_key == idempotency_key))
        existing_other_project_run = key_result.scalar_one_or_none()
        if existing_other_project_run is not None:
            raise HTTPException(status_code=409, detail="Idempotency-Key already used for a different project")

    start_node = "IngestPrompt"
    if body and body.resume_from_node:
        # Validate the requested resume node exists
        if body.resume_from_node not in ALL_NODE_NAMES:
            raise HTTPException(status_code=422, detail=f"Unknown node: {body.resume_from_node}")
        start_node = body.resume_from_node

    run = ProjectRun(
        project_id=project_id,
        status=ProjectStatus.IDEATION,
        current_node=start_node,
        idempotency_key=idempotency_key,
    )
    db.add(run)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if not idempotency_key:
            raise exc

        existing_result = await db.execute(select(ProjectRun).where(ProjectRun.idempotency_key == idempotency_key))
        existing_run = existing_result.scalar_one_or_none()
        if existing_run and existing_run.project_id == project_id:
            return existing_run
        raise HTTPException(status_code=409, detail="Idempotency-Key already used for a different project") from exc
    await db.refresh(run)

    # Enqueue orchestrator processing as a background task
    background_tasks.add_task(_run_orchestrator_background, run.id)

    return run
