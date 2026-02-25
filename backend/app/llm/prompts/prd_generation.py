"""Prompt templates for PRD generation.

Used by the ``GeneratePRD`` orchestrator node to produce a Product
Requirements Document from the user's initial prompt.
"""
from __future__ import annotations

from typing import Any

_SYSTEM_PROMPT = """\
You are an expert product manager and technical writer.  Your job is to
produce a clear, comprehensive Product Requirements Document (PRD) for a
software project based on the user's description.

You MUST respond with a single JSON object (no markdown fences, no preamble)
matching this exact schema:

{
  "executive_summary": "string — one-paragraph project overview",
  "user_stories": [
    {"persona": "string", "action": "string", "benefit": "string"}
  ],
  "scope_boundaries": {
    "in_scope": ["string"],
    "out_of_scope": ["string"]
  },
  "entity_list": [
    {"name": "string", "description": "string"}
  ],
  "non_goals": ["string"]
}

Requirements:
- executive_summary: concise paragraph covering purpose, target users, and value.
- user_stories: at least 3 stories in "As a <persona>, I want <action> so that <benefit>" form.
- scope_boundaries: explicit in-scope and out-of-scope items.
- entity_list: key domain entities/objects the system will manage.
- non_goals: items explicitly excluded from this project.

Write in professional, concise English.
Return ONLY valid JSON — no markdown, no commentary.
"""

_USER_PROMPT = """\
Create a PRD for the following project idea:

{initial_prompt}
"""

_USER_PROMPT_WITH_FEEDBACK = """\
The previous PRD was rejected.  Revise it to address the feedback.

Feedback: {feedback}

Previous PRD:
{previous_prd}

Original project idea:
{initial_prompt}
"""


def build_prompts(
    *,
    initial_prompt: str,
    feedback: str | None = None,
    previous_artifacts: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for PRD generation.

    Parameters
    ----------
    initial_prompt:
        The raw user prompt describing the project idea.
    feedback:
        Optional rejection feedback from a previous PRD review cycle.
    previous_artifacts:
        Previous artifact content dict — used to include the rejected PRD
        when regenerating after rejection.
    """
    if feedback:
        import json

        prev_prd = ""
        if previous_artifacts and "prd" in previous_artifacts:
            prd_data = previous_artifacts["prd"]
            # Strip internal metadata before including in prompt
            prd_clean = {
                k: v
                for k, v in prd_data.items()
                if not k.startswith("__")
            }
            prev_prd = json.dumps(prd_clean, indent=2)

        user_prompt = _USER_PROMPT_WITH_FEEDBACK.format(
            initial_prompt=initial_prompt,
            feedback=feedback,
            previous_prd=prev_prd or "(no previous PRD available)",
        )
    else:
        user_prompt = _USER_PROMPT.format(initial_prompt=initial_prompt)

    return _SYSTEM_PROMPT, user_prompt
