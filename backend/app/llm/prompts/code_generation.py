"""Prompt templates for phased code generation."""
from __future__ import annotations

import json
from typing import Any

_SYSTEM_PROMPT_FULL = """\
You are an expert full-stack software engineer. Given approved artifacts, generate
production-quality project code.

Rules:
1. Follow the technology stack and architecture from the tech plan exactly.
2. Produce complete, runnable files; no placeholders.
3. Include dependency manifests and runtime configuration.
4. Every local import must resolve to another file in the set.
5. Never include secrets. Use environment variables.
6. Ensure deploy-baseline artifacts exist:
   - Vercel/frontend: package manifest plus runtime entry file.
   - Supabase: SQL migrations when schema requires DB changes.
   - Environment template: `.env.example` placeholders only.

You MUST return a single valid JSON object:
{
  "files": [
    {"path": "relative/path/to/file.ext", "content": "full file contents", "language": "python"}
  ],
  "build_command": "npm run build",
  "test_command": "npm test",
  "entry_point": "backend/app/main.py"
}

Return ONLY JSON.
"""

_SYSTEM_PROMPT_CHUNK = """\
You are an expert full-stack software engineer. Generate ONE phased chunk of files.

Rules:
1. Output only files for the requested phase.
2. Use complete, production-ready content.
3. Do not include secrets; use env vars.
4. Keep imports consistent with already-generated files and file inventory.
5. Return only valid JSON with this shape:
{
  "files": [
    {"path": "relative/path/to/file.ext", "content": "full file contents", "language": "python"}
  ]
}
6. Every relative JS/TS import must resolve to a generated file path.
7. Use stable paths under `frontend/`, `backend/`, `db/` or `supabase/`.
8. Ensure deploy-baseline artifacts exist across phases:
   - Vercel/frontend: `package.json` (root or frontend) plus at least one frontend runtime entry file.
   - Supabase: SQL migrations in `supabase/migrations/` or `db/migrations/` when schema requires DB changes.
   - Environment template: `.env.example` with placeholders (never real secrets).

Return ONLY JSON.
"""

_USER_PROMPT_FULL = """\
Generate the complete source code for the project based on the following artifacts.

## Technical Plan
{tech_plan_content}

## Design Specification
{design_spec_content}

## PRD Summary
{prd_content}

Generate ALL files needed for a working project: backend code, frontend code, \
configuration files, database migrations, and dependency manifests.  Follow the \
folder structure from the tech plan.
"""

_USER_PROMPT_WITH_FEEDBACK_FULL = """\
Generate revised source code. A previous version was rejected by the security
gate. Fix these security issues:
{feedback}

## Technical Plan
{tech_plan_content}

## Design Specification
{design_spec_content}

## PRD Summary
{prd_content}

## Previous Code Snapshot
{previous_code}

Fix all findings without regressions. Return the complete updated file set.
"""

_USER_PROMPT_CHUNK = """\
Generate only the {chunk_label} files for this project.

Chunk-specific requirements:
{chunk_requirements}

## Technical Plan
{tech_plan_content}

## Design Specification
{design_spec_content}

## PRD Summary
{prd_content}

## Files generated in previous chunks
{generated_files}

## Current file path inventory (authoritative)
{generated_file_index}
{security_feedback_block}
{previous_code_block}
Return only JSON with a `files` array for this phase.
"""

_CHUNK_REQUIREMENTS = {
    "backend": (
        "Create backend API routes, domain models, and services using tech plan "
        "`api_routes` and `database_schema`. If backend is required, include "
        "`backend/app/main.py` as an executable entrypoint and ensure Python imports resolve."
    ),
    "frontend": (
        "Create frontend pages/components using tech plan `component_hierarchy` "
        "and design `screens`. Ensure every relative import points to an emitted file "
        "(hooks, store, api, pages, components)."
    ),
    "config": (
        "Create configuration/manifests (requirements/package manifests, Docker, env examples, "
        "framework config files) needed to build and run. Include deploy-ready config for "
        "Vercel and env placeholders for Supabase public keys when applicable."
    ),
    "migrations": (
        "Create database migration files aligned with the defined schema. Prefer "
        "`supabase/migrations/*.sql` (or `db/migrations/*.sql`) so deploy can apply them."
    ),
}


def _serialize(artifact: Any) -> str:
    """Best-effort serialisation of an artifact dict to a prompt string."""
    if isinstance(artifact, dict):
        cleaned = {k: v for k, v in artifact.items() if not k.startswith("__")}
        return json.dumps(cleaned, indent=2)
    return str(artifact) if artifact else "(not provided)"


def _serialize_code_snapshot(artifact: Any) -> str:
    """Serialize a previous code snapshot for inclusion in feedback prompts."""
    if not isinstance(artifact, dict):
        return "(no previous code)"
    files = artifact.get("files", [])
    if not files:
        return "(no previous code)"
    parts = []
    for f in files[:30]:  # Cap to avoid blowing up token budget
        parts.append(f"### {f.get('path', '?')}\n```{f.get('language', '')}\n{f.get('content', '')}\n```")
    return "\n\n".join(parts)


def _serialize_generated_files(files: list[dict[str, Any]] | None) -> str:
    """Serialize previously generated chunk files with conservative truncation."""
    if not files:
        return "(none yet)"

    parts: list[str] = []
    for file_data in files[:20]:
        path = file_data.get("path", "?")
        language = file_data.get("language", "")
        content = str(file_data.get("content", ""))
        if len(content) > 2000:
            content = content[:2000] + "\n# ...truncated for context..."
        parts.append(f"### {path}\n```{language}\n{content}\n```")
    return "\n\n".join(parts)


def _serialize_generated_file_index(files: list[dict[str, Any]] | None) -> str:
    """Serialize a compact list of generated paths for import/dependency planning."""
    if not files:
        return "(none yet)"

    paths = sorted(
        {
            str(file_data.get("path", "")).strip()
            for file_data in files
            if str(file_data.get("path", "")).strip()
        }
    )
    if not paths:
        return "(none yet)"

    max_paths = 400
    display = paths[:max_paths]
    lines = [f"- {path}" for path in display]
    if len(paths) > max_paths:
        lines.append(f"- ... ({len(paths) - max_paths} more paths omitted)")
    return "\n".join(lines)


def build_prompts(
    *,
    previous_artifacts: dict[str, Any] | None = None,
    feedback: str | None = None,
    chunk: str = "full_snapshot",
    generated_files: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for code generation.

    Parameters
    ----------
    previous_artifacts:
        Should contain ``"tech_plan"`` and optionally ``"design_spec"`` and ``"prd"``.
    feedback:
        Optional security-gate findings from a previous code review.
    chunk:
        Generation scope. Use one of ``backend``, ``frontend``, ``config``,
        ``migrations`` for phased generation; default ``full_snapshot``.
    generated_files:
        Files already generated in previous phases for context.
    """
    arts = previous_artifacts or {}
    tech_plan = _serialize(arts.get("tech_plan"))
    design_spec = _serialize(arts.get("design_spec"))
    prd = _serialize(arts.get("prd"))

    if chunk == "full_snapshot":
        if feedback:
            previous_code = _serialize_code_snapshot(arts.get("code_snapshot"))
            user_prompt = _USER_PROMPT_WITH_FEEDBACK_FULL.format(
                tech_plan_content=tech_plan,
                design_spec_content=design_spec,
                prd_content=prd,
                feedback=feedback,
                previous_code=previous_code,
            )
        else:
            user_prompt = _USER_PROMPT_FULL.format(
                tech_plan_content=tech_plan,
                design_spec_content=design_spec,
                prd_content=prd,
            )
        return _SYSTEM_PROMPT_FULL, user_prompt

    chunk_requirements = _CHUNK_REQUIREMENTS.get(chunk, _CHUNK_REQUIREMENTS["backend"])
    security_feedback_block = ""
    previous_code_block = ""
    if feedback:
        security_feedback_block = f"\n## Security Remediation (MUST FIX)\nFix these security issues:\n{feedback}\n"
        previous_code = _serialize_code_snapshot(arts.get("code_snapshot"))
        previous_code_block = f"\n## Previous Code Snapshot\n{previous_code}\n"

    user_prompt = _USER_PROMPT_CHUNK.format(
        chunk_label=chunk,
        chunk_requirements=chunk_requirements,
        tech_plan_content=tech_plan,
        design_spec_content=design_spec,
        prd_content=prd,
        generated_files=_serialize_generated_files(generated_files),
        generated_file_index=_serialize_generated_file_index(generated_files),
        security_feedback_block=security_feedback_block,
        previous_code_block=previous_code_block,
    )

    return _SYSTEM_PROMPT_CHUNK, user_prompt


def build_full_snapshot_prompts(
    *,
    previous_artifacts: dict[str, Any] | None = None,
    feedback: str | None = None,
) -> tuple[str, str]:
    """Compatibility wrapper for existing tests/callers expecting full mode."""
    return build_prompts(
        previous_artifacts=previous_artifacts,
        feedback=feedback,
        chunk="full_snapshot",
    )


def build_chunk_prompts(
    *,
    chunk: str,
    previous_artifacts: dict[str, Any] | None = None,
    feedback: str | None = None,
    generated_files: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Convenience wrapper for phased generation prompts."""
    return build_prompts(
        previous_artifacts=previous_artifacts,
        feedback=feedback,
        chunk=chunk,
        generated_files=generated_files,
    )
