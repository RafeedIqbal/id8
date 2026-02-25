from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.models.enums import DesignProvider, ModelProfile


class DesignGenerateRequest(BaseModel):
    provider: DesignProvider
    model_profile: ModelProfile
    prompt_constraints: dict[str, Any] | None = None


class DesignFeedbackRequest(BaseModel):
    target_screen_id: str | None = None
    target_component_id: str | None = None
    feedback_text: str
