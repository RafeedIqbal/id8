"""GenerateTechPlan node handler.

Calls the LLM to produce a structured technical plan artifact from the
approved PRD and design artifacts.  On re-generation (after rejection) the
prompt includes the rejection feedback so the model can revise.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage, ArtifactType
from app.models.project_artifact import ProjectArtifact
from app.observability import emit_llm_usage_event
from app.orchestrator.base import NodeHandler, NodeResult, RunContext

logger = logging.getLogger("id8.orchestrator.handlers.generate_tech_plan")

# How many times to retry when the LLM returns invalid JSON.
_MAX_PARSE_RETRIES = 1


async def generate_with_fallback(*args: Any, **kwargs: Any) -> Any:
    """Late-bound wrapper to avoid llm/orchestrator circular imports in tests."""
    from app.llm.client import generate_with_fallback as _generate_with_fallback

    return await _generate_with_fallback(*args, **kwargs)


class GenerateTechPlanHandler(NodeHandler):
    """Generate a structured technical plan via LLM."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        from app.llm.prompts.tech_plan_generation import build_prompts
        from app.llm.router import resolve_profile

        # 1. Verify we have the required approved inputs.
        prd = _clean_artifact_content(ctx.previous_artifacts.get("prd"))
        if not prd:
            return NodeResult(
                outcome="failure",
                error="No approved PRD artifact available",
            )
        design = _clean_artifact_content(ctx.previous_artifacts.get("design_spec"))
        if not design:
            return NodeResult(
                outcome="failure",
                error="No approved design artifact available",
            )

        # 2. Check for rejection feedback (re-generation case)
        feedback = await _load_rejection_feedback(ctx)

        # 3. Capture artifact lineage for traceability.
        source_artifacts = await _load_source_artifact_references(ctx)

        # 3. Build prompts
        profile = resolve_profile(ctx.current_node)
        system_prompt, user_prompt = build_prompts(
            previous_artifacts={
                **ctx.previous_artifacts,
                "prd": prd,
                "design_spec": design,
            },
            feedback=feedback,
        )

        # 4. Call LLM with retry on parse failure.
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
            await emit_llm_usage_event(
                project_id=ctx.project_id,
                run_id=ctx.run_id,
                node=ctx.current_node,
                model_profile=llm_response.profile_used,
                model_id=llm_response.model_id,
                prompt_tokens=llm_response.token_usage.prompt_tokens,
                completion_tokens=llm_response.token_usage.completion_tokens,
                db=ctx.db,
            )

            # 5. Parse and validate
            plan_data, parse_error = _parse_tech_plan_response(llm_response.content)
            if plan_data is not None:
                plan_data["__tech_plan_metadata"] = {
                    "source_artifacts": source_artifacts,
                    "rejection_feedback": feedback or "",
                }
                logger.info(
                    "Generated tech plan for project=%s (attempt=%d, model=%s)",
                    ctx.project_id,
                    attempt + 1,
                    llm_response.model_id,
                )
                return NodeResult(
                    outcome="success",
                    artifact_data=plan_data,
                    llm_response=llm_response,
                )

            last_error = parse_error
            logger.warning(
                "Tech plan parse failed (attempt %d/%d): %s",
                attempt + 1,
                _MAX_PARSE_RETRIES + 1,
                parse_error,
            )

        # All parse retries exhausted.
        logger.error(
            "Tech plan generation failed schema validation after retries: %s",
            last_error,
        )
        return NodeResult(
            outcome="failure",
            error=f"Tech plan schema validation failed after retries: {last_error}",
        )


async def _load_rejection_feedback(ctx: RunContext) -> str | None:
    """Load the most recent rejection notes for the tech_plan stage, if any."""
    result = await ctx.db.execute(
        select(ApprovalEvent)
        .where(
            ApprovalEvent.run_id == ctx.run_id,
            ApprovalEvent.stage == ApprovalStage.TECH_PLAN,
            ApprovalEvent.decision == "rejected",
        )
        .order_by(ApprovalEvent.created_at.desc())
        .limit(1)
    )
    event = result.scalar_one_or_none()
    if event is not None and event.notes:
        return event.notes
    return None


def _clean_artifact_content(raw: Any) -> dict[str, Any]:
    """Return a metadata-stripped artifact dict or ``{}`` when invalid."""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("__")}


async def _load_source_artifact_references(ctx: RunContext) -> dict[str, dict[str, Any]]:
    """Return PRD + design artifact references used in this run."""
    refs: dict[str, dict[str, Any]] = {}

    for key, artifact_type in (
        ("prd", ArtifactType.PRD),
        ("design_spec", ArtifactType.DESIGN_SPEC),
    ):
        result = await ctx.db.execute(
            select(ProjectArtifact)
            .where(
                ProjectArtifact.run_id == ctx.run_id,
                ProjectArtifact.artifact_type == artifact_type,
            )
            .order_by(ProjectArtifact.version.desc())
            .limit(1)
        )
        artifact = result.scalar_one_or_none()
        refs[key] = {
            "artifact_type": str(artifact_type),
            "artifact_id": str(artifact.id) if artifact is not None else "",
            "run_id": str(artifact.run_id) if artifact is not None else "",
            "version": artifact.version if artifact is not None else 0,
        }

    return refs


def _parse_tech_plan_response(content: str) -> tuple[dict | None, str | None]:
    """Try to parse the LLM response into a validated tech plan dict.

    Returns ``(plan_dict, None)`` on success or ``(None, error_message)``
    on failure.
    """
    from app.schemas.tech_plan import TechPlanContent

    # Strip markdown fences if the model wrapped the JSON
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"

    try:
        plan = TechPlanContent.model_validate(raw)
    except ValidationError as exc:
        return None, f"Schema validation failed: {exc}"

    return plan.model_dump(), None
