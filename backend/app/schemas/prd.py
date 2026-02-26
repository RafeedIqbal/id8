"""PRD output schema — validates LLM-generated PRD content.

Used by the ``GeneratePRD`` handler to parse and validate the structured
JSON produced by the model.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UserStory(BaseModel):
    persona: str = Field(..., description="Who is the user")
    action: str = Field(..., description="What they want to do")
    benefit: str = Field(..., description="Why they want to do it")


class ScopeBoundaries(BaseModel):
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class Entity(BaseModel):
    name: str
    description: str


class PrdContent(BaseModel):
    """Structured PRD produced by the LLM."""

    executive_summary: str
    user_stories: list[UserStory]
    scope_boundaries: ScopeBoundaries
    entity_list: list[Entity]
    non_goals: list[str]
    dummy_data_spec: list[dict[str, Any]] = Field(default_factory=list)
