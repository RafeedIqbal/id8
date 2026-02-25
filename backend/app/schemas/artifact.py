from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import ArtifactType, ModelProfile


class ProjectArtifactResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    artifact_type: ArtifactType
    version: int
    content: dict[str, Any]
    model_profile: ModelProfile | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ArtifactResponse(BaseModel):
    artifact: ProjectArtifactResponse


class ArtifactListResponse(BaseModel):
    items: list[ProjectArtifactResponse]
