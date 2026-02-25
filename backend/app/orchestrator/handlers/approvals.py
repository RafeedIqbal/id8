"""Approval wait-node handler for the ID8 orchestrator.

A single handler class is used for all four HITL gates (PRD, Design,
Tech Plan, Deploy).  It queries the most recent ``ApprovalEvent`` for
the current run + stage and returns the appropriate outcome.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage
from app.orchestrator.base import NodeHandler, NodeResult, RunContext
from app.orchestrator.nodes import NodeName

# Maps each wait-node to the ApprovalStage it corresponds to.
_WAIT_NODE_TO_STAGE: dict[str, ApprovalStage] = {
    NodeName.WAIT_PRD_APPROVAL: ApprovalStage.PRD,
    NodeName.WAIT_DESIGN_APPROVAL: ApprovalStage.DESIGN,
    NodeName.WAIT_TECH_PLAN_APPROVAL: ApprovalStage.TECH_PLAN,
    NodeName.WAIT_DEPLOY_APPROVAL: ApprovalStage.DEPLOY,
}


class WaitApprovalHandler(NodeHandler):
    """Check for a matching approval event and surface its decision.

    Returns one of:
    * ``outcome="approved"`` — approval found with decision "approved"
    * ``outcome="rejected"`` — approval found with decision "rejected"
    * ``outcome="waiting"`` — no approval event yet; engine should park the run
    """

    async def execute(self, ctx: RunContext) -> NodeResult:
        stage = _WAIT_NODE_TO_STAGE.get(ctx.current_node)
        if stage is None:
            return NodeResult(outcome="waiting", error=f"Unknown wait node: {ctx.current_node}")

        result = await ctx.db.execute(
            select(ApprovalEvent)
            .where(
                ApprovalEvent.run_id == ctx.run_id,
                ApprovalEvent.stage == stage,
            )
            .order_by(ApprovalEvent.created_at.desc())
            .limit(1)
        )
        event = result.scalar_one_or_none()

        if event is None:
            return NodeResult(outcome="waiting")

        return NodeResult(outcome=event.decision)
