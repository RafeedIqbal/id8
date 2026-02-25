"""Prompt templates for internal_spec design generation.

Used by the ``InternalSpecProvider`` to produce a screen-by-screen design
specification via the LLM when Stitch MCP is unavailable.
"""
from __future__ import annotations

import json
from typing import Any

_SYSTEM_PROMPT = """\
You are an expert UI/UX designer and front-end architect.  Your job is to
produce a detailed, screen-by-screen design specification for a web
application based on the approved PRD.

You MUST respond with a single JSON object (no markdown fences, no preamble)
matching this exact schema:

{
  "screens": [
    {
      "id": "string — unique screen identifier (e.g. screen-1)",
      "name": "string — human-readable screen name",
      "description": "string — purpose and layout overview",
      "components": [
        {
          "id": "string — unique component id (e.g. comp-1)",
          "name": "string — component name",
          "type": "string — component type (e.g. header, form, table, card, button, nav)",
          "properties": {
            "label": "optional string",
            "placeholder": "optional string",
            "variant": "optional string"
          }
        }
      ],
      "assets": ["optional list of asset references"]
    }
  ]
}

Requirements:
- Generate screens covering all key user flows described in the PRD.
- Each screen should have a meaningful name and description.
- Include all interactive components (forms, buttons, navigation, tables, etc).
- Use consistent component IDs across related screens.
- Prefer modern, accessible design patterns.
- Return ONLY valid JSON — no markdown, no commentary.
"""

_USER_PROMPT = """\
Create a screen-by-screen design specification for this product:

Executive Summary:
{executive_summary}

User Stories:
{user_stories}

Domain Entities:
{entities}

Scope Boundaries:
{scope_boundaries}

Non-goals:
{non_goals}

Design Constraints:
{constraints}
"""

_USER_PROMPT_WITH_FEEDBACK = """\
The previous design was rejected.  Revise it to address the feedback.

Feedback: {feedback}

{target_info}

Previous Design:
{previous_design}

Original PRD Context:
Executive Summary: {executive_summary}

User Stories:
{user_stories}

Domain Entities:
{entities}

Scope Boundaries:
{scope_boundaries}

Non-goals:
{non_goals}

Design Constraints:
{constraints}
"""


def build_prompts(
    *,
    prd_content: dict[str, Any],
    constraints: dict[str, Any] | None = None,
    feedback: str | None = None,
    target_screen_id: str | None = None,
    target_component_id: str | None = None,
    previous_design: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for design generation."""
    summary = prd_content.get("executive_summary", "")
    stories = _format_user_stories(prd_content.get("user_stories", []))
    entities = _format_entities(prd_content.get("entity_list", []))
    scope_boundaries = _format_scope_boundaries(prd_content.get("scope_boundaries", {}))
    non_goals = _format_non_goals(prd_content.get("non_goals", []))
    constraints_text = json.dumps(constraints, indent=2) if constraints else "(none)"

    if feedback:
        target_parts = []
        if target_screen_id:
            target_parts.append(f"Target Screen: {target_screen_id}")
        if target_component_id:
            target_parts.append(f"Target Component: {target_component_id}")
        target_info = "\n".join(target_parts) if target_parts else ""

        prev_text = json.dumps(previous_design, indent=2) if previous_design else "(none)"

        user_prompt = _USER_PROMPT_WITH_FEEDBACK.format(
            executive_summary=summary,
            user_stories=stories,
            entities=entities,
            scope_boundaries=scope_boundaries,
            non_goals=non_goals,
            constraints=constraints_text,
            feedback=feedback,
            target_info=target_info,
            previous_design=prev_text,
        )
    else:
        user_prompt = _USER_PROMPT.format(
            executive_summary=summary,
            user_stories=stories,
            entities=entities,
            scope_boundaries=scope_boundaries,
            non_goals=non_goals,
            constraints=constraints_text,
        )

    return _SYSTEM_PROMPT, user_prompt


def _format_user_stories(stories: list[dict[str, Any]]) -> str:
    if not stories:
        return "(none)"
    lines = []
    for s in stories:
        persona = s.get("persona", "user")
        action = s.get("action", "")
        benefit = s.get("benefit", "")
        lines.append(f"- As a {persona}, I want to {action} so that {benefit}")
    return "\n".join(lines)


def _format_entities(entities: list[dict[str, Any]]) -> str:
    if not entities:
        return "(none)"
    return ", ".join(e.get("name", "") for e in entities)


def _format_scope_boundaries(boundaries: dict[str, Any]) -> str:
    if not boundaries:
        return "(none)"

    lines: list[str] = []
    in_scope = boundaries.get("in_scope", [])
    out_of_scope = boundaries.get("out_of_scope", [])

    if in_scope:
        lines.append("In scope:")
        lines.extend(f"- {item}" for item in in_scope)
    if out_of_scope:
        lines.append("Out of scope:")
        lines.extend(f"- {item}" for item in out_of_scope)

    return "\n".join(lines) if lines else "(none)"


def _format_non_goals(non_goals: list[str]) -> str:
    if not non_goals:
        return "(none)"
    return "\n".join(f"- {goal}" for goal in non_goals)
