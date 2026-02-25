from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import ModelProfile, ProjectStatus


class CreateRunRequest(BaseModel):
    resume_from_node: str | None = None
    model_profile: ModelProfile | None = None


class ProjectRunResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: ProjectStatus
    current_node: str
    idempotency_key: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
