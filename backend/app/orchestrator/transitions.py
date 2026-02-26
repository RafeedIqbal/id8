"""Transition table for the ID8 orchestrator state machine.

Encodes the full node graph from orchestration/state-machine.md as a flat
dictionary.  Each key is a non-terminal NodeName, and the value is a mapping
of outcome → next NodeName.
"""
from __future__ import annotations

from app.orchestrator.nodes import NodeName

# Outcome keys: success, approved, rejected, passed, failed
TRANSITIONS: dict[NodeName, dict[str, NodeName]] = {
    NodeName.INGEST_PROMPT: {"success": NodeName.GENERATE_PRD, "failure": NodeName.END_FAILED},
    NodeName.GENERATE_PRD: {"success": NodeName.WAIT_PRD_APPROVAL, "failure": NodeName.END_FAILED},
    NodeName.WAIT_PRD_APPROVAL: {"approved": NodeName.GENERATE_DESIGN, "rejected": NodeName.GENERATE_PRD},
    NodeName.GENERATE_DESIGN: {
        "success": NodeName.WAIT_DESIGN_APPROVAL,
        "failure": NodeName.END_FAILED,
    },
    NodeName.WAIT_DESIGN_APPROVAL: {"approved": NodeName.GENERATE_TECH_PLAN, "rejected": NodeName.GENERATE_DESIGN},
    NodeName.GENERATE_TECH_PLAN: {"success": NodeName.WAIT_TECH_PLAN_APPROVAL, "failure": NodeName.END_FAILED},
    NodeName.WAIT_TECH_PLAN_APPROVAL: {"approved": NodeName.WRITE_CODE, "rejected": NodeName.GENERATE_TECH_PLAN},
    NodeName.WRITE_CODE: {"success": NodeName.SECURITY_GATE, "failure": NodeName.END_FAILED},
    NodeName.SECURITY_GATE: {"passed": NodeName.PREPARE_PR, "failed": NodeName.WRITE_CODE, "failure": NodeName.END_FAILED},
    NodeName.PREPARE_PR: {"success": NodeName.WAIT_DEPLOY_APPROVAL, "failure": NodeName.END_FAILED},
    NodeName.WAIT_DEPLOY_APPROVAL: {"approved": NodeName.DEPLOY_PRODUCTION, "rejected": NodeName.END_FAILED},
    NodeName.DEPLOY_PRODUCTION: {"passed": NodeName.END_SUCCESS, "failed": NodeName.END_FAILED, "failure": NodeName.END_FAILED},
}


class InvalidTransitionError(Exception):
    """Raised when no transition exists for the given node + outcome."""


def resolve_next_node(current_node: str, outcome: str) -> str:
    """Return the next node name for *current_node* given *outcome*.

    Raises ``InvalidTransitionError`` if the combination is not in the table.
    """
    try:
        node = NodeName(current_node)
    except ValueError as exc:
        raise InvalidTransitionError(f"No transitions defined for node '{current_node}'") from exc

    outcomes = TRANSITIONS.get(node)
    if outcomes is None:
        raise InvalidTransitionError(f"No transitions defined for node '{current_node}'")
    next_node = outcomes.get(outcome)
    if next_node is None:
        raise InvalidTransitionError(f"No transition for node '{current_node}' with outcome '{outcome}'")
    return str(next_node)


# Backwards compatibility for older imports.
InvalidTransition = InvalidTransitionError
