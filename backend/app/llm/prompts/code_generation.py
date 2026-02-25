"""Prompt templates for code generation.

Used by the ``WriteCode`` orchestrator node to produce source files from
the approved tech plan and design specification.
"""
from __future__ import annotations

import json
from typing import Any

_SYSTEM_PROMPT = """\
You are an expert full-stack software engineer.  Given an approved
Technical Plan and optional Design Specification, generate production-
quality source code that implements the described project.

Guidelines:
1. Follow the technology stack and architecture from the tech plan exactly.
2. Produce complete, runnable files — not snippets or placeholders.
3. Include sensible defaults, error handling, and inline comments.
4. Write idiomatic code for the chosen language/framework.
5. Include a dependency manifest (e.g. requirements.txt or package.json).
6. Include configuration files needed to build and run the project.
7. Every import must resolve to another file in the set or a declared dependency.
8. Do NOT include secrets, API keys, or credentials — use environment variables.

You MUST return your output as a single valid JSON object matching this schema:

{
  "files": [
    {"path": "relative/path/to/file.ext", "content": "full file contents", "language": "python"},
    ...
  ],
  "build_command": "npm run build",
  "test_command": "npm test",
  "entry_point": "backend/app/main.py"
}

Return ONLY the JSON object — no markdown fences, no preamble, no commentary.
"""

_USER_PROMPT = """\
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

_USER_PROMPT_WITH_FEEDBACK = """\
Generate revised source code.  A previous version was rejected by the security \
gate with the findings shown below — fix EVERY issue while keeping the project \
fully functional.

## Technical Plan
{tech_plan_content}

## Design Specification
{design_spec_content}

## PRD Summary
{prd_content}

## Security Findings (MUST FIX)
{feedback}

## Previous Code Snapshot
{previous_code}

Fix all security findings.  Do not introduce regressions.  Return the complete \
updated file set.
"""


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


def build_prompts(
    *,
    previous_artifacts: dict[str, Any] | None = None,
    feedback: str | None = None,
) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for code generation.

    Parameters
    ----------
    previous_artifacts:
        Should contain ``"tech_plan"`` and optionally ``"design_spec"`` and ``"prd"``.
    feedback:
        Optional security-gate findings from a previous code review.
    """
    arts = previous_artifacts or {}
    tech_plan = _serialize(arts.get("tech_plan"))
    design_spec = _serialize(arts.get("design_spec"))
    prd = _serialize(arts.get("prd"))

    if feedback:
        previous_code = _serialize_code_snapshot(arts.get("code_snapshot"))
        user_prompt = _USER_PROMPT_WITH_FEEDBACK.format(
            tech_plan_content=tech_plan,
            design_spec_content=design_spec,
            prd_content=prd,
            feedback=feedback,
            previous_code=previous_code,
        )
    else:
        user_prompt = _USER_PROMPT.format(
            tech_plan_content=tech_plan,
            design_spec_content=design_spec,
            prd_content=prd,
        )

    return _SYSTEM_PROMPT, user_prompt
