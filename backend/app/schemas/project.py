from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import ProjectStatus


class CreateProjectRequest(BaseModel):
    initial_prompt: str
    constraints: dict | None = None


class ProjectResponse(BaseModel):
    id: uuid.UUID
    initial_prompt: str
    status: ProjectStatus
    github_repo_url: str | None = None
    live_deployment_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
