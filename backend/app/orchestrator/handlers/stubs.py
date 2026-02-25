"""Stub node handlers for the ID8 orchestrator.

These return placeholder artifacts so the state machine can be exercised
end-to-end.  Real implementations are introduced in later tasks (05-09).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.orchestrator.base import NodeHandler, NodeResult, RunContext


class IngestPromptHandler(NodeHandler):
    """Extract the prompt from the project and pass it forward."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        result = await ctx.db.execute(select(Project).where(Project.id == ctx.project_id))
        project = result.scalar_one()
        return NodeResult(
            outcome="success",
            artifact_data={"prompt": project.initial_prompt, "source": "ingest"},
        )


class GeneratePRDHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="success",
            artifact_data={"title": "Placeholder PRD", "sections": [], "source": "stub"},
        )


class GenerateDesignHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="success",
            artifact_data={"title": "Placeholder Design Spec", "components": [], "source": "stub"},
        )


class GenerateTechPlanHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="success",
            artifact_data={"title": "Placeholder Tech Plan", "phases": [], "source": "stub"},
        )


class WriteCodeHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="success",
            artifact_data={"files": [], "loc": 0, "source": "stub"},
        )


class SecurityGateHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="passed",
            artifact_data={"findings": [], "critical": 0, "high": 0, "source": "stub"},
        )


class PreparePRHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="success",
            artifact_data={"branch": "feat/auto-generated", "pr_url": None, "source": "stub"},
        )


class DeployProductionHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="passed",
            artifact_data={"live_url": None, "environment": "production", "source": "stub"},
        )


class EndSuccessHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(outcome="terminal_success")


class EndFailedHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(outcome="terminal_failed")


# ---------------------------------------------------------------------------
# Helper used by the approval handler to resolve the approval stage for a
# given wait node, kept here to avoid circular imports.
# ---------------------------------------------------------------------------

_WAIT_NODE_TO_ARTIFACT_TYPE: dict[str, str] = {
    "IngestPrompt": "prd",
    "GeneratePRD": "prd",
    "GenerateDesign": "design_spec",
    "GenerateTechPlan": "tech_plan",
    "WriteCode": "code_snapshot",
    "SecurityGate": "security_report",
    "PreparePR": "deploy_report",
    "DeployProduction": "deploy_report",
}


def artifact_type_for_node(node_name: str) -> str | None:
    """Return the ArtifactType value associated with *node_name*, or None."""
    return _WAIT_NODE_TO_ARTIFACT_TYPE.get(node_name)
