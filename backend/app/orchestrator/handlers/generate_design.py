"""GenerateDesign node handler.

Generates a design specification via the design provider layer (Stitch MCP
primary, internal_spec fallback).  On re-generation after rejection, loads
feedback from the latest rejection event and calls provider.regenerate().
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.design.auth_resolver import get_default_stitch_auth
from app.design.base import (
    DesignFeedback,
    DesignOutput,
    Screen,
    ScreenComponent,
    StitchAuthError,
)
from app.design.provider_factory import generate_with_fallback, regenerate_with_fallback
from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage, ArtifactType, DesignProvider, ModelProfile
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.observability import emit_audit_event, emit_llm_usage_event
from app.orchestrator.base import NodeHandler, NodeResult, RunContext

logger = logging.getLogger("id8.orchestrator.handlers.generate_design")


class GenerateDesignHandler(NodeHandler):
    """Generate a design spec from an approved PRD."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        # 1. Load project
        result = await ctx.db.execute(
            select(Project).where(Project.id == ctx.project_id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            return NodeResult(outcome="failure", error=f"Project {ctx.project_id} not found")

        # 2. Load approved PRD artifact content
        prd_content = _extract_prd_content(ctx.previous_artifacts)
        if not prd_content:
            return NodeResult(outcome="failure", error="No approved PRD artifact found")

        # 3. Extract provider preference and constraints.
        payload = ctx.workflow_payload or {}
        pending = _extract_pending_config(ctx.previous_artifacts)
        preferred_provider = (
            payload.get("design_provider")
            or pending.get("provider")
            or DesignProvider.STITCH_MCP
        )
        preferred_provider_name = str(preferred_provider)
        constraints = payload.get("design_constraints") or pending.get("design_constraints", {})
        auth = get_default_stitch_auth()

        # 4. Check for rejection feedback (re-generation case)
        pending_feedback = _extract_pending_feedback(pending)
        feedback_text = pending_feedback.get("feedback_text") or await _load_rejection_feedback(ctx)

        try:
            if feedback_text:
                # Re-generation after rejection
                previous_design = await _load_previous_design(ctx)
                feedback = DesignFeedback(
                    feedback_text=feedback_text,
                    target_screen_id=(
                        pending_feedback.get("target_screen_id")
                        or payload.get("target_screen_id")
                    ),
                    target_component_id=(
                        pending_feedback.get("target_component_id")
                        or payload.get("target_component_id")
                    ),
                )
                output, provider_used = await regenerate_with_fallback(
                    previous=previous_design,
                    feedback=feedback,
                    auth=auth,
                    preferred_provider=preferred_provider,
                )
            else:
                # Initial generation
                output, provider_used = await generate_with_fallback(
                    prd_content=prd_content,
                    constraints=constraints,
                    auth=auth,
                    preferred_provider=preferred_provider,
                )
        except StitchAuthError as exc:
            # Return auth error as a structured failure the frontend can act on
            logger.warning("AUDIT design_auth_error project=%s: %s", ctx.project_id, exc)
            return NodeResult(
                outcome="failure",
                error=str(exc),
                artifact_data=exc.action_payload,
            )

        # 5. Build artifact content
        artifact_data = output.to_dict()
        artifact_data["__design_metadata"] = {
            "provider_used": provider_used,
            **(output.metadata or {}),
        }
        if (
            preferred_provider_name == str(DesignProvider.STITCH_MCP)
            and str(provider_used) == str(DesignProvider.INTERNAL_SPEC)
        ):
            await emit_audit_event(
                ctx.project_id,
                None,
                "design.provider_fallback",
                {
                    "run_id": str(ctx.run_id),
                    "node": ctx.current_node,
                    "from_provider": DesignProvider.STITCH_MCP,
                    "to_provider": DesignProvider.INTERNAL_SPEC,
                },
                ctx.db,
            )

        llm_meta = output.metadata or {}
        total_estimated_cost_usd = 0.0
        llm_usage_records = _extract_llm_usage_records(llm_meta)
        for usage in llm_usage_records:
            total_estimated_cost_usd += await emit_llm_usage_event(
                project_id=ctx.project_id,
                run_id=ctx.run_id,
                node=ctx.current_node,
                model_profile=usage["profile"],
                model_id=usage["model_id"],
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                db=ctx.db,
            )
        if llm_usage_records:
            artifact_data["__design_metadata"]["estimated_cost_usd"] = round(total_estimated_cost_usd, 8)
        if feedback_text:
            artifact_data["__design_metadata"]["feedback_applied"] = feedback_text

        logger.info(
            "Generated design for project=%s provider=%s screens=%d",
            ctx.project_id,
            provider_used,
            len(output.screens),
        )

        return NodeResult(
            outcome="success",
            artifact_data=artifact_data,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_prd_content(previous_artifacts: dict[str, Any]) -> dict[str, Any]:
    """Extract the PRD content from previous artifacts, stripping metadata."""
    prd = previous_artifacts.get("prd")
    if not isinstance(prd, dict):
        return {}
    return {k: v for k, v in prd.items() if not k.startswith("__")}


def _extract_pending_config(previous_artifacts: dict[str, Any]) -> dict[str, Any]:
    """Extract config from a pending design_spec artifact (created by the route)."""
    design = previous_artifacts.get("design_spec")
    if isinstance(design, dict) and design.get("status") == "pending":
        return design
    return {}


def _extract_pending_feedback(pending: dict[str, Any]) -> dict[str, Any]:
    feedback_text = pending.get("feedback")
    if not isinstance(feedback_text, str) or not feedback_text.strip():
        return {}
    return {
        "feedback_text": feedback_text.strip(),
        "target_screen_id": pending.get("target_screen_id"),
        "target_component_id": pending.get("target_component_id"),
    }


async def _load_previous_design(ctx: RunContext) -> DesignOutput:
    """Load the latest completed design artifact for this project."""
    result = await ctx.db.execute(
        select(ProjectArtifact)
        .where(
            ProjectArtifact.project_id == ctx.project_id,
            ProjectArtifact.artifact_type == ArtifactType.DESIGN_SPEC,
        )
        .order_by(ProjectArtifact.version.desc())
    )

    design: dict[str, Any] | None = None
    metadata: dict[str, Any] = {}
    for artifact in result.scalars():
        content = artifact.content
        if not isinstance(content, dict):
            continue
        if content.get("status") == "pending":
            continue
        design = content
        raw_meta = content.get("__design_metadata")
        if isinstance(raw_meta, dict):
            metadata = raw_meta
        break

    if design is None:
        design = ctx.previous_artifacts.get("design_spec")
    if not isinstance(design, dict):
        return DesignOutput()
    if not metadata and isinstance(design.get("__design_metadata"), dict):
        metadata = design["__design_metadata"]

    screens: list[Screen] = []
    for rs in design.get("screens", []):
        if not isinstance(rs, dict):
            continue
        components = []
        for rc in rs.get("components", []):
            if not isinstance(rc, dict):
                continue
            components.append(ScreenComponent(
                id=rc.get("id", ""),
                name=rc.get("name", ""),
                type=rc.get("type", ""),
                properties=rc.get("properties", {}),
            ))
        screens.append(Screen(
            id=rs.get("id", ""),
            name=rs.get("name", ""),
            description=rs.get("description", ""),
            components=components,
            assets=rs.get("assets", []),
        ))

    return DesignOutput(screens=screens, metadata=metadata)


async def _load_rejection_feedback(ctx: RunContext) -> str | None:
    """Load the most recent design rejection notes, if any."""
    result = await ctx.db.execute(
        select(ApprovalEvent)
        .where(
            ApprovalEvent.project_id == ctx.project_id,
            ApprovalEvent.stage == ApprovalStage.DESIGN,
            ApprovalEvent.decision == "rejected",
        )
        .order_by(ApprovalEvent.created_at.desc())
        .limit(1)
    )
    event = result.scalar_one_or_none()
    if event is not None and event.notes:
        return event.notes
    return None


def _coerce_int(raw: Any) -> int:
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return 0


def _extract_llm_usage_records(meta: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    raw_calls = meta.get("llm_calls")
    if isinstance(raw_calls, list):
        for call in raw_calls:
            if not isinstance(call, dict):
                continue
            model_id = str(call.get("model_id", "")).strip()
            if not model_id:
                continue
            profile_raw = str(call.get("profile_used", ModelProfile.CUSTOMTOOLS)).strip()
            try:
                profile = ModelProfile(profile_raw)
            except ValueError:
                profile = ModelProfile.CUSTOMTOOLS
            records.append(
                {
                    "profile": profile,
                    "model_id": model_id,
                    "prompt_tokens": _coerce_int(call.get("prompt_tokens")),
                    "completion_tokens": _coerce_int(call.get("completion_tokens")),
                }
            )

    if records:
        return records

    model_id = str(meta.get("model_id", "")).strip()
    if not model_id:
        return []

    profile_raw = str(meta.get("profile_used", ModelProfile.CUSTOMTOOLS)).strip()
    try:
        profile = ModelProfile(profile_raw)
    except ValueError:
        profile = ModelProfile.CUSTOMTOOLS

    return [
        {
            "profile": profile,
            "model_id": model_id,
            "prompt_tokens": _coerce_int(meta.get("prompt_tokens")),
            "completion_tokens": _coerce_int(meta.get("completion_tokens")),
        }
    ]
