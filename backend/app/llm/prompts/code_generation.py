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
1. Follow the technology stack and architecture from the tech plan.
2. Produce complete, runnable files — not snippets.
3. Include sensible defaults, error handling, and inline comments.
4. Emit file paths as Markdown headings (e.g. ``## src/app.py``) so the
   output can be parsed into individual files.
5. Write idiomatic code for the chosen language/framework.
6. Include a minimal README and dependency manifest (e.g. requirements.txt
   or package.json).

Return ONLY the code output — no preamble or meta-commentary.
"""

_USER_PROMPT = """\
Generate the source code for the project based on the following artifacts.

## Technical Plan
{tech_plan_content}

## Design Specification
{design_spec_content}
"""

_USER_PROMPT_WITH_FEEDBACK = """\
Generate revised source code.  A previous version was rejected by
the security gate with the findings shown below — fix every issue.

## Technical Plan
{tech_plan_content}

## Design Specification
{design_spec_content}

## Security Findings
{feedback}
"""


def _serialize(artifact: Any) -> str:
    """Best-effort serialisation of an artifact dict to a prompt string."""
    if isinstance(artifact, dict):
        return json.dumps(artifact, indent=2)
    return str(artifact) if artifact else "(not provided)"


def build_prompts(
    *,
    previous_artifacts: dict[str, Any] | None = None,
    feedback: str | None = None,
) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for code generation.

    Parameters
    ----------
    previous_artifacts:
        Should contain ``"tech_plan"`` and optionally ``"design_spec"``.
    feedback:
        Optional security-gate findings from a previous code review.
    """
    arts = previous_artifacts or {}
    tech_plan = _serialize(arts.get("tech_plan"))
    design_spec = _serialize(arts.get("design_spec"))

    if feedback:
        user_prompt = _USER_PROMPT_WITH_FEEDBACK.format(
            tech_plan_content=tech_plan,
            design_spec_content=design_spec,
            feedback=feedback,
        )
    else:
        user_prompt = _USER_PROMPT.format(
            tech_plan_content=tech_plan,
            design_spec_content=design_spec,
        )

    return _SYSTEM_PROMPT, user_prompt
