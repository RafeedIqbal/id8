"""GeneratePRD node handler.

Calls the LLM to produce a structured PRD artifact from the project's
initial prompt.  On re-generation (after rejection) the prompt includes
the rejection feedback and the previous PRD content so the model can revise.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import select

from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage
from app.models.project import Project
from app.orchestrator.base import NodeHandler, NodeResult, RunContext

if TYPE_CHECKING:
    from app.llm.client import LlmResponse

logger = logging.getLogger("id8.orchestrator.handlers.generate_prd")

# How many times to retry when the LLM returns invalid JSON.
_MAX_PARSE_RETRIES = 1


class GeneratePRDHandler(NodeHandler):
    """Generate a structured PRD via LLM."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        # Lazy imports to avoid circular dependency (llm.client ↔ orchestrator)
        from app.llm.client import generate_with_fallback
        from app.llm.prompts.prd_generation import build_prompts
        from app.llm.router import resolve_profile

        # 1. Load project prompt
        result = await ctx.db.execute(
            select(Project).where(Project.id == ctx.project_id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            return NodeResult(outcome="failure", error=f"Project {ctx.project_id} not found")

        initial_prompt = project.initial_prompt

        # 2. Check for rejection feedback (re-generation case)
        feedback = await _load_rejection_feedback(ctx)

        # 3. Build prompts
        profile = resolve_profile(ctx.current_node)
        system_prompt, user_prompt = build_prompts(
            initial_prompt=initial_prompt,
            feedback=feedback,
            previous_artifacts=ctx.previous_artifacts,
        )

        # 4. Call LLM with retry on parse failure
        last_error: str | None = None
        for attempt in range(_MAX_PARSE_RETRIES + 1):
            effective_system = system_prompt
            if attempt > 0 and last_error:
                effective_system += (
                    "\n\nIMPORTANT: Your previous response was not valid JSON. "
                    f"Error: {last_error}\n"
                    "You MUST return ONLY a valid JSON object, no markdown fences or extra text."
                )

            llm_response = await generate_with_fallback(
                profile=profile,
                node_name=ctx.current_node,
                prompt=user_prompt,
                system_prompt=effective_system,
            )

            # 5. Parse and validate
            prd_data, parse_error = _parse_prd_response(llm_response.content)
            if prd_data is not None:
                logger.info(
                    "Generated PRD for project=%s (attempt=%d, model=%s)",
                    ctx.project_id,
                    attempt + 1,
                    llm_response.model_id,
                )
                return NodeResult(
                    outcome="success",
                    artifact_data=prd_data,
                    llm_response=llm_response,
                )

            last_error = parse_error
            logger.warning(
                "PRD parse failed (attempt %d/%d): %s",
                attempt + 1,
                _MAX_PARSE_RETRIES + 1,
                parse_error,
            )

        # All parse retries exhausted — return the raw content as artifact anyway
        # so the run can be inspected, but mark it as unparsed.
        logger.error("PRD generation failed schema validation after retries")
        raw_content = _extract_raw_content(llm_response.content)
        return NodeResult(
            outcome="success",
            artifact_data={
                "__parse_error": last_error,
                "raw_content": raw_content,
            },
            llm_response=llm_response,
        )


async def _load_rejection_feedback(ctx: RunContext) -> str | None:
    """Load the most recent rejection notes for the PRD stage, if any."""
    result = await ctx.db.execute(
        select(ApprovalEvent)
        .where(
            ApprovalEvent.project_id == ctx.project_id,
            ApprovalEvent.stage == ApprovalStage.PRD,
            ApprovalEvent.decision == "rejected",
        )
        .order_by(ApprovalEvent.created_at.desc())
        .limit(1)
    )
    event = result.scalar_one_or_none()
    if event is not None and event.notes:
        return event.notes
    return None


def _parse_prd_response(content: str) -> tuple[dict | None, str | None]:
    """Try to parse the LLM response into a validated PRD dict.

    Returns ``(prd_dict, None)`` on success or ``(None, error_message)``
    on failure.
    """
    from app.schemas.prd import PrdContent

    # Strip markdown fences if the model wrapped the JSON
    text = content.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = text.index("\n") if "\n" in text else len(text)
        text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"

    try:
        prd = PrdContent.model_validate(raw)
    except ValidationError as exc:
        return None, f"Schema validation failed: {exc}"

    return prd.model_dump(), None


def _extract_raw_content(content: str) -> str:
    """Return a cleaned-up version of the raw LLM content for debugging."""
    # Limit stored raw content to prevent bloating the artifact
    max_chars = 10_000
    if len(content) > max_chars:
        return content[:max_chars] + "... [truncated]"
    return content
