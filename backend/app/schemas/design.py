from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.design.base import StitchAuthMethod
from app.models.enums import DesignProvider, ModelProfile


class StitchAuthPayload(BaseModel):
    auth_method: StitchAuthMethod = StitchAuthMethod.API_KEY
    api_key: str | None = None
    oauth_token: str | None = None
    goog_user_project: str | None = None


class DesignGenerateRequest(BaseModel):
    provider: DesignProvider = DesignProvider.STITCH_MCP
    model_profile: ModelProfile = ModelProfile.CUSTOMTOOLS
    prompt_constraints: dict[str, Any] | None = None
    stitch_auth: StitchAuthPayload | None = None


class DesignFeedbackRequest(BaseModel):
    target_screen_id: str | None = None
    target_component_id: str | None = None
    feedback_text: str
    stitch_auth: StitchAuthPayload | None = None


class ScreenComponentSchema(BaseModel):
    id: str
    name: str
    type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class ScreenSchema(BaseModel):
    id: str
    name: str
    description: str = ""
    components: list[ScreenComponentSchema] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)


class DesignOutputSchema(BaseModel):
    """Validates the design spec content produced by providers."""
    screens: list[ScreenSchema] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
