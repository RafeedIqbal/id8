from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.enums import ApprovalStage


class ApprovalRequest(BaseModel):
    stage: ApprovalStage
    decision: Literal["approved", "rejected"]
    notes: str | None = None


class ApprovalEventResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    stage: ApprovalStage
    decision: str
    notes: str | None = None
    created_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
