"""Stub node handlers for the ID8 orchestrator.

These return placeholder artifacts so the state machine can be exercised
end-to-end.  Real implementations are introduced in later tasks (05-09).
"""
from __future__ import annotations

from sqlalchemy import select

from app.models.enums import ArtifactType
from app.models.project import Project
from app.orchestrator.base import NodeHandler, NodeResult, RunContext


class IngestPromptHandler(NodeHandler):
    """Extract the prompt from the project and pass it forward."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        result = await ctx.db.execute(select(Project).where(Project.id == ctx.project_id))
        result.scalar_one()
        return NodeResult(outcome="success")


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
        return NodeResult(outcome="success")


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


# Helper used by the engine to determine which nodes persist an artifact.
_NODE_TO_ARTIFACT_TYPE: dict[str, ArtifactType] = {
    "GeneratePRD": ArtifactType.PRD,
    "GenerateDesign": ArtifactType.DESIGN_SPEC,
    "GenerateTechPlan": ArtifactType.TECH_PLAN,
    "WriteCode": ArtifactType.CODE_SNAPSHOT,
    "SecurityGate": ArtifactType.SECURITY_REPORT,
    "DeployProduction": ArtifactType.DEPLOY_REPORT,
}


def artifact_type_for_node(node_name: str) -> ArtifactType | None:
    """Return the ArtifactType value associated with *node_name*, or None."""
    return _NODE_TO_ARTIFACT_TYPE.get(node_name)
