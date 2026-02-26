from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.project import Project
from app.models.project_run import ProjectRun
from app.models.user import User
from app.schemas.project import CreateProjectRequest, ProjectListItem, ProjectListResponse, ProjectResponse

router = APIRouter(tags=["projects"])
_SCAFFOLD_OWNER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


async def _ensure_scaffold_owner(db: AsyncSession) -> uuid.UUID:
    result = await db.execute(select(User).where(User.id == _SCAFFOLD_OWNER_ID))
    user = result.scalar_one_or_none()
    if user:
        return user.id

    user = User(
        id=_SCAFFOLD_OWNER_ID,
        email="operator+scaffold@id8.local",
        role="operator",
    )
    db.add(user)
    await db.flush()
    return user.id


@router.post("/projects", operation_id="createProject", response_model=ProjectResponse, status_code=201)
async def create_project(body: CreateProjectRequest, db: AsyncSession = Depends(get_db)) -> Project:
    # TODO: resolve owner from auth context after auth integration.
    owner_user_id = await _ensure_scaffold_owner(db)
    project = Project(
        initial_prompt=body.initial_prompt,
        owner_user_id=owner_user_id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/projects", operation_id="listProjects", response_model=ProjectListResponse)
async def list_projects(db: AsyncSession = Depends(get_db)) -> dict[str, list[ProjectListItem]]:
    project_result = await db.execute(
        select(Project).order_by(Project.updated_at.desc(), Project.created_at.desc())
    )
    projects = list(project_result.scalars().all())
    if not projects:
        return {"items": []}

    project_ids = [project.id for project in projects]
    latest_runs_subq = (
        select(
            ProjectRun.id.label("id"),
            ProjectRun.project_id.label("project_id"),
            ProjectRun.status.label("status"),
            ProjectRun.current_node.label("current_node"),
            ProjectRun.updated_at.label("updated_at"),
            func.row_number()
            .over(
                partition_by=ProjectRun.project_id,
                order_by=ProjectRun.created_at.desc(),
            )
            .label("rn"),
        )
        .where(ProjectRun.project_id.in_(project_ids))
        .subquery()
    )

    run_result = await db.execute(select(latest_runs_subq).where(latest_runs_subq.c.rn == 1))
    latest_runs_by_project: dict[uuid.UUID, dict[str, object]] = {}
    for row in run_result:
        latest_runs_by_project[row.project_id] = {
            "id": row.id,
            "status": row.status,
            "current_node": row.current_node,
            "updated_at": row.updated_at,
        }

    items: list[ProjectListItem] = []
    for project in projects:
        payload = ProjectResponse.model_validate(project).model_dump()
        payload["latest_run"] = latest_runs_by_project.get(project.id)
        items.append(ProjectListItem.model_validate(payload))

    return {"items": items}


@router.get("/projects/{projectId}", operation_id="getProject", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID = Path(alias="projectId"),
    db: AsyncSession = Depends(get_db),
) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
