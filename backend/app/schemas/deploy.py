from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class DeployRequest(BaseModel):
    target: str = "production"
    artifact_id: uuid.UUID | None = None


class DeploymentRecordResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    environment: str
    status: str
    url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
