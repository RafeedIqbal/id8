from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DeployRequest(BaseModel):
    target: str = "production"
    artifact_id: uuid.UUID | None = None


class DeploymentRecord(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    environment: str
    status: str
    url: str | None = Field(default=None, validation_alias="deployment_url")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


DeploymentRecordResponse = DeploymentRecord
