"""Code snapshot schema — validates LLM-generated code output.

Used by the ``WriteCode`` handler to parse and validate the structured
JSON produced by the model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CodeFile(BaseModel):
    """A single generated source file."""

    path: str = Field(..., description='Relative file path, e.g. "backend/app/routes/users.py"')
    content: str = Field(..., description="Full file contents")
    language: str = Field(..., description="Language identifier: python, typescript, sql, etc.")


class CodeChunkContent(BaseModel):
    """Single phased generation chunk."""

    files: list[CodeFile] = Field(..., description="Files generated for the current phase")
    package_changes: dict[str, dict[str, str]] = Field(
        default_factory=lambda: {"dependencies": {},"devDependencies": {}},
        description="Package additions. Only add new packages, never return a full package.json."
    )

class CodeSnapshotContent(BaseModel):
    """Structured code snapshot produced by the LLM."""

    files: list[CodeFile] = Field(..., description="All generated source files")
    build_command: str = Field(default="npm run build", description='e.g. "npm run build"')
    test_command: str = Field(default="npm test", description='e.g. "npm test"')
    entry_point: str = Field(default="src/app/page.tsx", description='e.g. "src/app/page.tsx"')
    __code_metadata: dict[str, str | int | bool | dict] = Field(
        default_factory=dict, description="Internal merge and providence metadata"
    )
