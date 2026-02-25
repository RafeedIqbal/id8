"""Prompt templates for technical plan generation.

Used by the ``GenerateTechPlan`` orchestrator node to produce a structured
JSON technical plan from the approved PRD and design artifacts.
"""
from __future__ import annotations

import json
from typing import Any

_SYSTEM_PROMPT = """\
You are a senior software architect.  Given an approved PRD and design
specification, produce a detailed Technical Implementation Plan as a JSON
object that a development team can follow to build the project.

The JSON object MUST contain exactly these top-level keys:

1. **folder_structure** — a nested dict representing the project directory tree.
   Keys are directory/file names, values are either nested dicts (subdirectories)
   or short description strings (files).
2. **database_schema** — a dict where keys are table names and values are dicts
   describing columns, types, constraints, and relationships.
3. **api_routes** — an array of objects, each with "method" (HTTP verb),
   "path" (URL pattern), and "description" (what it does).
4. **component_hierarchy** — a nested dict representing the frontend component
   tree.  Keys are component names, values are nested dicts (children) or
   description strings (leaf components).
5. **dependencies** — an array of objects, each with "name" (package name)
   and "version" (version constraint string, e.g. "^2.0.0").
6. **deployment_config** — a dict describing infrastructure requirements,
   CI/CD, environments, and rollback strategy.

Return ONLY the JSON object — no markdown fences, no preamble, no commentary.
"""

_USER_PROMPT = """\
Generate a Technical Implementation Plan for the project described in the
following approved PRD and design specification.

## Approved PRD
{prd_content}

## Design Specification
{design_content}
"""

_USER_PROMPT_WITH_FEEDBACK = """\
Generate a revised Technical Implementation Plan.
Previous plan was rejected. Feedback: {feedback}
Address every feedback point in the new version.

## Approved PRD
{prd_content}

## Design Specification
{design_content}

## Previous Tech Plan
{previous_plan_content}
"""


def _serialize_artifact(artifact: Any) -> str:
    """Serialize an artifact dict to a string, stripping internal metadata."""
    if isinstance(artifact, dict):
        cleaned = {k: v for k, v in artifact.items() if not k.startswith("__")}
        return json.dumps(cleaned, indent=2)
    if artifact:
        return str(artifact)
    return "(not available)"


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
        May also contain a ``"design_spec"`` key with the approved design.
    feedback:
        Optional rejection feedback from a previous tech-plan review.
    """
    prd_content = "(not available)"
    design_content = "(not available)"

    if previous_artifacts:
        if "prd" in previous_artifacts:
            prd_content = _serialize_artifact(previous_artifacts["prd"])
        if "design_spec" in previous_artifacts:
            design_content = _serialize_artifact(previous_artifacts["design_spec"])

    if feedback:
        previous_plan_content = "(not available)"
        if previous_artifacts and "tech_plan" in previous_artifacts:
            previous_plan_content = _serialize_artifact(previous_artifacts["tech_plan"])
        user_prompt = _USER_PROMPT_WITH_FEEDBACK.format(
            prd_content=prd_content,
            design_content=design_content,
            feedback=feedback,
            previous_plan_content=previous_plan_content,
        )
    else:
        user_prompt = _USER_PROMPT.format(
            prd_content=prd_content,
            design_content=design_content,
        )

    return _SYSTEM_PROMPT, user_prompt
