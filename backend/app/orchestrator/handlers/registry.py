"""Handler registry — maps each NodeName to its concrete NodeHandler."""
from __future__ import annotations

from app.orchestrator.base import NodeHandler
from app.orchestrator.handlers.approvals import WaitApprovalHandler
from app.orchestrator.handlers.generate_design import GenerateDesignHandler
from app.orchestrator.handlers.generate_prd import GeneratePRDHandler
from app.orchestrator.handlers.ingest_prompt import IngestPromptHandler
from app.orchestrator.handlers.generate_tech_plan import GenerateTechPlanHandler
from app.orchestrator.handlers.prepare_pr import PreparePRHandler
from app.orchestrator.handlers.security_gate import SecurityGateHandler
from app.orchestrator.handlers.stubs import (
    DeployProductionHandler,
    EndFailedHandler,
    EndSuccessHandler,
)
from app.orchestrator.handlers.write_code import WriteCodeHandler
from app.orchestrator.nodes import NodeName

# Shared instance for all wait nodes.
_wait_handler = WaitApprovalHandler()

HANDLER_REGISTRY: dict[str, NodeHandler] = {
    NodeName.INGEST_PROMPT: IngestPromptHandler(),
    NodeName.GENERATE_PRD: GeneratePRDHandler(),
    NodeName.WAIT_PRD_APPROVAL: _wait_handler,
    NodeName.GENERATE_DESIGN: GenerateDesignHandler(),
    NodeName.WAIT_DESIGN_APPROVAL: _wait_handler,
    NodeName.GENERATE_TECH_PLAN: GenerateTechPlanHandler(),
    NodeName.WAIT_TECH_PLAN_APPROVAL: _wait_handler,
    NodeName.WRITE_CODE: WriteCodeHandler(),
    NodeName.SECURITY_GATE: SecurityGateHandler(),
    NodeName.PREPARE_PR: PreparePRHandler(),
    NodeName.WAIT_DEPLOY_APPROVAL: _wait_handler,
    NodeName.DEPLOY_PRODUCTION: DeployProductionHandler(),
    NodeName.END_SUCCESS: EndSuccessHandler(),
    NodeName.END_FAILED: EndFailedHandler(),
}
