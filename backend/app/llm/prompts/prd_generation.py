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

The PRD must include:
1. **Executive Summary** — one-paragraph overview.
2. **Problem Statement** — what pain-point or opportunity this addresses.
3. **Goals & Success Metrics** — measurable outcomes.
4. **User Personas** — at least two distinct personas.
5. **Functional Requirements** — numbered list of capabilities.
6. **Non-Functional Requirements** — performance, security, accessibility.
7. **Scope & Constraints** — what is explicitly out of scope.
8. **Timeline Estimate** — rough phases.

Write in professional, concise English.  Use Markdown formatting.
Return ONLY the PRD content — no preamble or meta-commentary.
"""

_USER_PROMPT = """\
Create a PRD for the following project idea:

{initial_prompt}
"""

_USER_PROMPT_WITH_FEEDBACK = """\
Create a revised PRD for the following project idea.  A previous version
was rejected with the feedback shown below — address every point.

## Project Idea
{initial_prompt}

## Reviewer Feedback
{feedback}
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
        Unused for PRD generation but accepted for interface consistency.
    """
    if feedback:
        user_prompt = _USER_PROMPT_WITH_FEEDBACK.format(
            initial_prompt=initial_prompt,
            feedback=feedback,
        )
    else:
        user_prompt = _USER_PROMPT.format(initial_prompt=initial_prompt)

    return _SYSTEM_PROMPT, user_prompt
