"""Prompt templates for technical plan generation.

Used by the ``GenerateTechPlan`` orchestrator node to produce a structured
JSON technical plan from the approved PRD and design artifacts.
"""

from __future__ import annotations

import json
from typing import Any

_SYSTEM_PROMPT = """\
You are a senior frontend architect. Produce a Technical Plan for a
**frontend-only Next.js prototype** deploying on Vercel. Zero backend.

All data is hardcoded dummy data. No API routes, no database, no server-side logic. The app must run out of the box.

Return a single JSON object with exactly these keys:

{
  "folder_structure": {
    "src/": {
      "app/": {"page.tsx": "landing/home page", "(routes)/": {"[route]/page.tsx": "description"}},
      "components/": {"ui/": "reusable UI primitives", "layout/": "nav, sidebar, footer"},
      "data/": "hardcoded dummy data files (typed arrays of mock objects)",
      "lib/": "utility helpers, cn(), formatters",
      "types/": "TypeScript interfaces for all entities"
    }
  },
  "routing": [
    {"path": "/", "component": "HomePage", "description": "string"}
  ],
  "component_hierarchy": {
    "RootLayout": {
      "Navigation": "persistent sidebar/topnav",
      "children": {"PageComponent": {"SubComponent": "description"}}
    }
  },
  "dummy_data_plan": [
    {"file": "src/data/users.ts", "entity": "User", "count": 10, "fields": ["id","name","email","avatar","role"]}
  ],
  "dependencies": [
    {"name": "string", "version": "string", "reason": "string"}
  ],
  "styling_strategy": {
    "framework": "tailwindcss",
    "animations": "framer-motion or CSS transitions",
    "icons": "lucide-react",
    "fonts": "Google Font name"
  }
}

Rules:
- folder_structure: Next.js App Router under src/app/. One page.tsx per route. Shared layouts.
- routing: every screen from design spec maps to a route. All client-side navigation.
- component_hierarchy: nested dict. Leaf values are short descriptions.
- dummy_data_plan: typed mock data files. Realistic sample counts (5-20 items). Include relationships.
- dependencies: only frontend packages. No backend libs. Include version + reason.
  MUST include: next, react, react-dom, tailwindcss, typescript.
  Recommended: framer-motion (animations), lucide-react (icons), clsx or tailwind-merge (styling).
- styling_strategy: Tailwind CSS is required. Specify animation library, icon set, font choice.
- NO database_schema, NO api_routes, NO server deployment config.

Return ONLY JSON.
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
