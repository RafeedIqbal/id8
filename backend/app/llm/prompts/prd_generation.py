"""Prompt templates for PRD generation.

Used by the ``GeneratePRD`` orchestrator node to produce a Product
Requirements Document from the user's initial prompt.
"""

from __future__ import annotations

import json
from typing import Any

_SYSTEM_PROMPT = """\
You are an expert product manager. Produce a PRD for a **frontend-only proof-of-concept** web app.

The app is a visual prototype: self-contained, no backend, no database, no auth, no API calls.
All data is hardcoded dummy data. Every screen is routable and
interactive. It deploys on Vercel as a static Next.js app.

Respond with a single JSON object (no markdown, no preamble):

{
  "executive_summary": "string — one paragraph: purpose, users, value prop",
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
  "non_goals": ["string"],
  "dummy_data_spec": [
    {"entity": "string", "sample_count": "number", "key_fields": ["string"]}
  ]
}

Rules:
- executive_summary: concise, mentions this is a frontend-only visual prototype.
- user_stories: 3+ stories focused on UI interactions (browsing, filtering, navigating, viewing details).
- scope_boundaries.out_of_scope MUST include: backend/API, database,
  authentication, data persistence, server-side logic.
- scope_boundaries.in_scope MUST include: client-side routing,
  interactive UI, dummy data, responsive design, animations.
- entity_list: domain entities the UI will display with hardcoded sample data.
- dummy_data_spec: for each entity, specify how many samples and key fields to generate.
- non_goals: real data, auth, payments, persistence, server-side rendering of dynamic data.

Return ONLY valid JSON.
"""

_USER_PROMPT = """\
Create a PRD for the following project idea:

{initial_prompt}

Constraints:
{constraints}
"""

_USER_PROMPT_WITH_FEEDBACK = """\
The previous PRD was rejected.  Revise it to address the feedback.

Feedback: {feedback}

Previous PRD:
{previous_prd}

Original project idea:
{initial_prompt}

Constraints:
{constraints}
"""


def build_prompts(
    *,
    initial_prompt: str,
    constraints: dict[str, Any] | None = None,
    feedback: str | None = None,
    previous_artifacts: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for PRD generation.

    Parameters
    ----------
    initial_prompt:
        The raw user prompt describing the project idea.
    constraints:
        Optional structured constraints supplied with the project request.
    feedback:
        Optional rejection feedback from a previous PRD review cycle.
    previous_artifacts:
        Previous artifact content dict — used to include the rejected PRD
        when regenerating after rejection.
    """
    constraints_text = _format_constraints(constraints)
    if feedback:
        prev_prd = ""
        if previous_artifacts and "prd" in previous_artifacts:
            prd_data = previous_artifacts["prd"]
            # Strip internal metadata before including in prompt
            prd_clean = {k: v for k, v in prd_data.items() if not k.startswith("__")}
            prev_prd = json.dumps(prd_clean, indent=2)

        user_prompt = _USER_PROMPT_WITH_FEEDBACK.format(
            initial_prompt=initial_prompt,
            constraints=constraints_text,
            feedback=feedback,
            previous_prd=prev_prd or "(no previous PRD available)",
        )
    else:
        user_prompt = _USER_PROMPT.format(
            initial_prompt=initial_prompt,
            constraints=constraints_text,
        )

    return _SYSTEM_PROMPT, user_prompt


def _format_constraints(constraints: dict[str, Any] | None) -> str:
    if not constraints:
        return "(none)"
    return json.dumps(constraints, indent=2, sort_keys=True)
