"""Prompt templates for technical plan generation.

Used by the ``GenerateTechPlan`` orchestrator node to produce an
implementation-ready technical plan from the approved PRD.
"""
from __future__ import annotations

import json
from typing import Any

_SYSTEM_PROMPT = """\
You are a senior software architect.  Given an approved PRD, produce a
detailed Technical Implementation Plan that a development team can
follow to build the project.

The plan must include:
1. **Architecture Overview** — high-level component diagram (described
   textually or in Mermaid).
2. **Technology Stack** — languages, frameworks, databases, services.
3. **Data Model** — entities, relationships, key constraints.
4. **API Surface** — endpoints / RPCs with request/response shapes.
5. **Implementation Phases** — ordered list of work packages with
   estimated effort.
6. **Security Considerations** — auth, secrets, data protection.
7. **Testing Strategy** — unit, integration, E2E approach.
8. **Deployment Plan** — CI/CD, environments, rollback.

Write in professional, concise English.  Use Markdown formatting.
Return ONLY the technical plan — no preamble or meta-commentary.
"""

_USER_PROMPT = """\
Generate a Technical Implementation Plan for the project described in
the following approved PRD:

{prd_content}
"""

_USER_PROMPT_WITH_FEEDBACK = """\
Generate a revised Technical Implementation Plan.  A previous version
was rejected with the feedback shown below — address every point.

## Approved PRD
{prd_content}

## Reviewer Feedback
{feedback}
"""


def build_prompts(
    *,
    previous_artifacts: dict[str, Any] | None = None,
    feedback: str | None = None,
) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for tech plan generation.

    Parameters
    ----------
    previous_artifacts:
        Must contain a ``"prd"`` key with the approved PRD content dict.
    feedback:
        Optional rejection feedback from a previous tech-plan review.
    """
    prd_content = ""
    if previous_artifacts and "prd" in previous_artifacts:
        prd_raw = previous_artifacts["prd"]
        if isinstance(prd_raw, dict):
            prd_content = json.dumps(prd_raw, indent=2)
        else:
            prd_content = str(prd_raw)

    if feedback:
        user_prompt = _USER_PROMPT_WITH_FEEDBACK.format(
            prd_content=prd_content,
            feedback=feedback,
        )
    else:
        user_prompt = _USER_PROMPT.format(prd_content=prd_content)

    return _SYSTEM_PROMPT, user_prompt
