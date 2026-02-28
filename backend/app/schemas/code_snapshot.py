"""Code snapshot schema — validates LLM-generated code output.

Used by the ``WriteCode`` handler to parse and validate the structured
JSON produced by the model.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def _default_package_requirements() -> list["PackageRequirement"]:
    return []


class CodeFile(BaseModel):
    """A single generated source file."""

    path: str = Field(..., description='Relative file path, e.g. "backend/app/routes/users.py"')
    content: str = Field(..., description="Full file contents")
    language: str = Field(..., description="Language identifier: python, typescript, sql, etc.")


class PackageRequirement(BaseModel):
    """A package the model needs, without allowing it to choose the version."""

    name: str = Field(..., description='Package name, e.g. "lucide-react"')
    section: Literal["dependencies", "devDependencies"] = Field(
        default="dependencies",
        description='Dependency section, either "dependencies" or "devDependencies"',
    )
    reason: str = Field(
        default="",
        description="Short justification for why the package is needed",
    )


class CodeChunkContent(BaseModel):
    """Single phased generation chunk."""

    files: list[CodeFile] = Field(..., description="Files generated for the current phase")
    package_requirements: list[PackageRequirement] = Field(
        default_factory=_default_package_requirements,
        description="Package intents. Only add package names and sections, never versions or a full package.json.",
    )

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_package_changes(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "package_requirements" in data:
            return data

        legacy = data.get("package_changes")
        if not isinstance(legacy, dict):
            return data

        requirements: list[dict[str, str]] = []
        for section in ("dependencies", "devDependencies"):
            packages = legacy.get(section, {})
            if not isinstance(packages, dict):
                continue
            for name in packages:
                requirements.append({"name": str(name), "section": section})

        upgraded = dict(data)
        upgraded["package_requirements"] = requirements
        return upgraded


class CodeSnapshotContent(BaseModel):
    """Structured code snapshot produced by the LLM."""

    files: list[CodeFile] = Field(..., description="All generated source files")
    build_command: str = Field(default="npm run build", description='e.g. "npm run build"')
    test_command: str = Field(
        default="npx tsc --noEmit && npm run lint",
        description='e.g. "npx tsc --noEmit && npm run lint"',
    )
    entry_point: str = Field(default="app/page.tsx", description='e.g. "app/page.tsx"')
    code_metadata_: dict[str, Any] = Field(
        default_factory=dict, alias="__code_metadata", description="Internal merge and providence metadata"
    )
