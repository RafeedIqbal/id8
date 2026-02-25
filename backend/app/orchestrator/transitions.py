"""Transition table for the ID8 orchestrator state machine.

Encodes the full node graph from orchestration/state-machine.md as a flat
dictionary.  Each key is a non-terminal NodeName, and the value is a mapping
of outcome → next NodeName.
"""
from __future__ import annotations

from app.orchestrator.nodes import NodeName

# Outcome keys: success, approved, rejected, passed, failed
TRANSITIONS: dict[str, dict[str, str]] = {
    NodeName.INGEST_PROMPT: {"success": NodeName.GENERATE_PRD},
    NodeName.GENERATE_PRD: {"success": NodeName.WAIT_PRD_APPROVAL},
    NodeName.WAIT_PRD_APPROVAL: {"approved": NodeName.GENERATE_DESIGN, "rejected": NodeName.GENERATE_PRD},
    NodeName.GENERATE_DESIGN: {"success": NodeName.WAIT_DESIGN_APPROVAL},
    NodeName.WAIT_DESIGN_APPROVAL: {"approved": NodeName.GENERATE_TECH_PLAN, "rejected": NodeName.GENERATE_DESIGN},
    NodeName.GENERATE_TECH_PLAN: {"success": NodeName.WAIT_TECH_PLAN_APPROVAL},
    NodeName.WAIT_TECH_PLAN_APPROVAL: {"approved": NodeName.WRITE_CODE, "rejected": NodeName.GENERATE_TECH_PLAN},
    NodeName.WRITE_CODE: {"success": NodeName.SECURITY_GATE},
    NodeName.SECURITY_GATE: {"passed": NodeName.PREPARE_PR, "failed": NodeName.WRITE_CODE},
    NodeName.PREPARE_PR: {"success": NodeName.WAIT_DEPLOY_APPROVAL},
    NodeName.WAIT_DEPLOY_APPROVAL: {"approved": NodeName.DEPLOY_PRODUCTION, "rejected": NodeName.END_FAILED},
    NodeName.DEPLOY_PRODUCTION: {"passed": NodeName.END_SUCCESS, "failed": NodeName.END_FAILED},
}


class InvalidTransition(Exception):
    """Raised when no transition exists for the given node + outcome."""


def resolve_next_node(current_node: str, outcome: str) -> str:
    """Return the next node name for *current_node* given *outcome*.

    Raises ``InvalidTransition`` if the combination is not in the table.
    """
    outcomes = TRANSITIONS.get(current_node)
    if outcomes is None:
        raise InvalidTransition(f"No transitions defined for node '{current_node}'")
    next_node = outcomes.get(outcome)
    if next_node is None:
        raise InvalidTransition(f"No transition for node '{current_node}' with outcome '{outcome}'")
    return next_node
