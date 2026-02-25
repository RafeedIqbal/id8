"""GenerateDesign node handler.

Generates a design specification via the design provider layer (Stitch MCP
primary, internal_spec fallback).  On re-generation after rejection, loads
feedback from the latest rejection event and calls provider.regenerate().
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.design.auth_cache import get_cached_stitch_auth
from app.design.base import (
    DesignFeedback,
    DesignOutput,
    Screen,
    ScreenComponent,
    StitchAuthContext,
    StitchAuthError,
)
from app.design.provider_factory import generate_with_fallback, regenerate_with_fallback
from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage, ArtifactType, DesignProvider
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
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

        # 3. Extract provider preference and auth from workflow_payload or
        #    from a pending design_spec artifact created by the /design/generate route
        payload = ctx.workflow_payload or {}
        pending = _extract_pending_config(ctx.previous_artifacts)
        preferred_provider = (
            payload.get("design_provider")
            or pending.get("provider")
            or DesignProvider.STITCH_MCP
        )
        constraints = payload.get("design_constraints") or pending.get("design_constraints", {})
        auth = (
            _extract_auth(payload)
            or _extract_auth(pending)
            or get_cached_stitch_auth(ctx.run_id)
        )

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
    for artifact in result.scalars():
        content = artifact.content
        if not isinstance(content, dict):
            continue
        if content.get("status") == "pending":
            continue
        design = content
        break

    if design is None:
        design = ctx.previous_artifacts.get("design_spec")
    if not isinstance(design, dict):
        return DesignOutput()

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

    return DesignOutput(screens=screens)


def _extract_auth(payload: dict[str, Any]) -> StitchAuthContext | None:
    """Build a StitchAuthContext from the workflow payload, if credentials present."""
    auth_data = payload.get("stitch_auth")
    if not isinstance(auth_data, dict):
        return None
    return StitchAuthContext.from_mapping(auth_data)


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
