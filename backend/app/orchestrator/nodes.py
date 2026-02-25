"""Node registry for the ID8 orchestrator state machine.

Defines the 14 canonical nodes, their metadata, and the mapping from
node → ProjectStatus so the engine can keep projects.status in sync.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

from app.models.enums import ProjectStatus


class NodeName(enum.StrEnum):
    INGEST_PROMPT = "IngestPrompt"
    GENERATE_PRD = "GeneratePRD"
    WAIT_PRD_APPROVAL = "WaitPRDApproval"
    GENERATE_DESIGN = "GenerateDesign"
    WAIT_DESIGN_APPROVAL = "WaitDesignApproval"
    GENERATE_TECH_PLAN = "GenerateTechPlan"
    WAIT_TECH_PLAN_APPROVAL = "WaitTechPlanApproval"
    WRITE_CODE = "WriteCode"
    SECURITY_GATE = "SecurityGate"
    PREPARE_PR = "PreparePR"
    WAIT_DEPLOY_APPROVAL = "WaitDeployApproval"
    DEPLOY_PRODUCTION = "DeployProduction"
    END_SUCCESS = "EndSuccess"
    END_FAILED = "EndFailed"


@dataclass(frozen=True, slots=True)
class NodeMeta:
    name: NodeName
    next_on_success: NodeName | None = None
    next_on_failure: NodeName | None = None
    is_wait_node: bool = False
    is_terminal: bool = False
    # Only idempotent nodes should be skipped when an artifact checkpoint exists.
    is_idempotent: bool = False


NODE_REGISTRY: dict[NodeName, NodeMeta] = {
    NodeName.INGEST_PROMPT: NodeMeta(
        NodeName.INGEST_PROMPT,
        next_on_success=NodeName.GENERATE_PRD,
        next_on_failure=NodeName.END_FAILED,
        is_idempotent=True,
    ),
    NodeName.GENERATE_PRD: NodeMeta(
        NodeName.GENERATE_PRD,
        next_on_success=NodeName.WAIT_PRD_APPROVAL,
        next_on_failure=NodeName.END_FAILED,
    ),
    NodeName.WAIT_PRD_APPROVAL: NodeMeta(
        NodeName.WAIT_PRD_APPROVAL,
        next_on_success=NodeName.GENERATE_DESIGN,
        next_on_failure=NodeName.GENERATE_PRD,
        is_wait_node=True,
    ),
    NodeName.GENERATE_DESIGN: NodeMeta(
        NodeName.GENERATE_DESIGN,
        next_on_success=NodeName.WAIT_DESIGN_APPROVAL,
        next_on_failure=NodeName.END_FAILED,
    ),
    NodeName.WAIT_DESIGN_APPROVAL: NodeMeta(
        NodeName.WAIT_DESIGN_APPROVAL,
        next_on_success=NodeName.GENERATE_TECH_PLAN,
        next_on_failure=NodeName.GENERATE_DESIGN,
        is_wait_node=True,
    ),
    NodeName.GENERATE_TECH_PLAN: NodeMeta(
        NodeName.GENERATE_TECH_PLAN,
        next_on_success=NodeName.WAIT_TECH_PLAN_APPROVAL,
        next_on_failure=NodeName.END_FAILED,
    ),
    NodeName.WAIT_TECH_PLAN_APPROVAL: NodeMeta(
        NodeName.WAIT_TECH_PLAN_APPROVAL,
        next_on_success=NodeName.WRITE_CODE,
        next_on_failure=NodeName.GENERATE_TECH_PLAN,
        is_wait_node=True,
    ),
    NodeName.WRITE_CODE: NodeMeta(
        NodeName.WRITE_CODE,
        next_on_success=NodeName.SECURITY_GATE,
        next_on_failure=NodeName.END_FAILED,
    ),
    NodeName.SECURITY_GATE: NodeMeta(
        NodeName.SECURITY_GATE,
        next_on_success=NodeName.PREPARE_PR,
        next_on_failure=NodeName.WRITE_CODE,
    ),
    NodeName.PREPARE_PR: NodeMeta(
        NodeName.PREPARE_PR,
        next_on_success=NodeName.WAIT_DEPLOY_APPROVAL,
        next_on_failure=NodeName.END_FAILED,
        is_idempotent=True,
    ),
    NodeName.WAIT_DEPLOY_APPROVAL: NodeMeta(
        NodeName.WAIT_DEPLOY_APPROVAL,
        next_on_success=NodeName.DEPLOY_PRODUCTION,
        next_on_failure=NodeName.END_FAILED,
        is_wait_node=True,
    ),
    NodeName.DEPLOY_PRODUCTION: NodeMeta(
        NodeName.DEPLOY_PRODUCTION,
        next_on_success=NodeName.END_SUCCESS,
        next_on_failure=NodeName.END_FAILED,
        is_idempotent=True,
    ),
    NodeName.END_SUCCESS: NodeMeta(NodeName.END_SUCCESS, is_terminal=True),
    NodeName.END_FAILED: NodeMeta(NodeName.END_FAILED, is_terminal=True),
}

# Maps each node to the ProjectStatus that projects.status should be set to
# when the run is currently at (or entering) that node.
NODE_TO_PROJECT_STATUS: dict[NodeName, ProjectStatus] = {
    NodeName.INGEST_PROMPT: ProjectStatus.IDEATION,
    NodeName.GENERATE_PRD: ProjectStatus.PRD_DRAFT,
    NodeName.WAIT_PRD_APPROVAL: ProjectStatus.PRD_DRAFT,
    NodeName.GENERATE_DESIGN: ProjectStatus.DESIGN_DRAFT,
    NodeName.WAIT_DESIGN_APPROVAL: ProjectStatus.DESIGN_DRAFT,
    NodeName.GENERATE_TECH_PLAN: ProjectStatus.TECH_PLAN_DRAFT,
    NodeName.WAIT_TECH_PLAN_APPROVAL: ProjectStatus.TECH_PLAN_DRAFT,
    NodeName.WRITE_CODE: ProjectStatus.CODEGEN,
    NodeName.SECURITY_GATE: ProjectStatus.SECURITY_GATE,
    NodeName.PREPARE_PR: ProjectStatus.DEPLOY_READY,
    NodeName.WAIT_DEPLOY_APPROVAL: ProjectStatus.DEPLOY_READY,
    NodeName.DEPLOY_PRODUCTION: ProjectStatus.DEPLOYING,
    NodeName.END_SUCCESS: ProjectStatus.DEPLOYED,
    NodeName.END_FAILED: ProjectStatus.FAILED,
}

ALL_NODE_NAMES: set[str] = {n.value for n in NodeName}
