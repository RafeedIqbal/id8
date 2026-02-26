from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import ProjectStatus


class CreateProjectRequest(BaseModel):
    initial_prompt: str
    constraints: dict[str, Any] | None = None


class ProjectRunSummary(BaseModel):
    id: uuid.UUID
    status: ProjectStatus
    current_node: str
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Project(BaseModel):
    id: uuid.UUID
    owner_user_id: uuid.UUID
    initial_prompt: str
    status: ProjectStatus
    github_repo_url: str | None = None
    live_deployment_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectListItem(Project):
    latest_run: ProjectRunSummary | None = None


class ProjectListResponse(BaseModel):
    items: list[ProjectListItem]


ProjectResponse = Project
