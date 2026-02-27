"""Base types for orchestrator node handlers.

Defines the ``RunContext`` that is passed into every handler, the
``NodeResult`` that every handler must return, and the abstract
``NodeHandler`` interface.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.llm.client import LlmResponse


@dataclass(slots=True)
class RunContext:
    """Immutable snapshot of state passed to each node handler."""

    run_id: uuid.UUID
    project_id: uuid.UUID
    current_node: str
    attempt: int
    db_session: AsyncSession
    previous_artifacts: dict[str, Any] = field(default_factory=dict)
    workflow_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def db(self) -> AsyncSession:
        """Backwards-compatible alias for existing handlers."""
        return self.db_session


@dataclass(slots=True)
class NodeResult:
    """Value returned by a node handler after execution.

    * ``outcome`` drives the transition table (e.g. "success", "approved").
    * ``artifact_data`` is optional JSONB content to persist as a ProjectArtifact.
    * ``context_updates`` carries ephemeral payload for downstream nodes in this run.
    * ``llm_response`` carries model/token telemetry for artifact persistence.
    * ``error`` is an optional message stored on the run when the node fails.
    """

    outcome: str
    artifact_data: dict[str, Any] | None = field(default=None)
    context_updates: dict[str, Any] | None = field(default=None)
    llm_response: LlmResponse | None = field(default=None)
    error: str | None = field(default=None)


class NodeHandler(ABC):
    """Contract that every node handler must implement."""

    @abstractmethod
    async def execute(self, context: RunContext) -> NodeResult:
        """Execute the node logic and return the result."""
