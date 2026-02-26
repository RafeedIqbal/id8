from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ModelProfile, ProjectStatus


class ReplayMode(StrEnum):
    RETRY_FAILED = "retry_failed"
    REPLAY_FROM_NODE = "replay_from_node"


class CreateRunRequest(BaseModel):
    resume_from_node: str | None = None
    model_profile: ModelProfile | None = None
    replay_mode: ReplayMode | None = None


class ProjectRun(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: ProjectStatus
    current_node: str
    idempotency_key: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunTimelineEvent(BaseModel):
    event_type: str
    from_node: str | None = None
    to_node: str
    outcome: str | None = None
    created_at: datetime


class ProjectRunDetail(ProjectRun):
    timeline: list[RunTimelineEvent] = Field(default_factory=list)


ProjectRunResponse = ProjectRun
ProjectRunDetailResponse = ProjectRunDetail
