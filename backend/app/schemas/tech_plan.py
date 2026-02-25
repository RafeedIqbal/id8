"""Tech plan output schema — validates LLM-generated technical plan content.

Used by the ``GenerateTechPlan`` handler to parse and validate the structured
JSON produced by the model.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ApiRoute(BaseModel):
    method: str = Field(..., description="HTTP method (GET, POST, PUT, DELETE, etc.)")
    path: str = Field(..., description="URL path pattern")
    description: str = Field(..., description="What the endpoint does")


class Dependency(BaseModel):
    name: str = Field(..., description="Package or service name")
    version: str = Field(default="", description="Version constraint")


class TechPlanContent(BaseModel):
    """Structured technical plan produced by the LLM."""

    folder_structure: dict[str, Any] = Field(
        ..., description="Directory tree for the project"
    )
    database_schema: dict[str, Any] = Field(
        ..., description="Tables, columns, and relationships"
    )
    api_routes: list[ApiRoute] = Field(
        ..., description="API endpoints with method, path, description"
    )
    component_hierarchy: dict[str, Any] = Field(
        ..., description="Frontend component tree"
    )
    dependencies: list[Dependency] = Field(
        ..., description="Packages with version constraints"
    )
    deployment_config: dict[str, Any] = Field(
        ..., description="Infrastructure and deployment requirements"
    )
