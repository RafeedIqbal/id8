from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import DesignProvider, ModelProfile


class DesignGenerateRequest(BaseModel):
    provider: DesignProvider = DesignProvider.STITCH_MCP
    model_profile: ModelProfile = ModelProfile.CUSTOMTOOLS
    prompt_constraints: dict[str, Any] | None = None


class DesignFeedbackRequest(BaseModel):
    target_screen_id: str | None = None
    target_component_id: str | None = None
    feedback_text: str


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
