from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.project import CreateProjectRequest, ProjectResponse

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
