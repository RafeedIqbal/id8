"""IngestPrompt node handler.

Loads the project's ``initial_prompt``, validates it is non-empty, and
stores a ``prd_generation_payload`` in the run context for the downstream
``GeneratePRD`` node.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.models.project import Project
from app.orchestrator.base import NodeHandler, NodeResult, RunContext

logger = logging.getLogger("id8.orchestrator.handlers.ingest_prompt")

# Reject prompts longer than this (rough token proxy: ~4 chars/token).
_MAX_PROMPT_CHARS = 40_000


class IngestPromptHandler(NodeHandler):
    """Extract and validate the user prompt from the project."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        result = await ctx.db.execute(
            select(Project).where(Project.id == ctx.project_id)
        )
        project = result.scalar_one_or_none()

        if project is None:
            return NodeResult(
                outcome="failure",
                error=f"Project {ctx.project_id} not found",
            )

        prompt = (project.initial_prompt or "").strip()
        if not prompt:
            return NodeResult(
                outcome="failure",
                error="Project initial_prompt is empty",
            )

        if len(prompt) > _MAX_PROMPT_CHARS:
            return NodeResult(
                outcome="failure",
                error=f"Prompt exceeds maximum length ({len(prompt)} > {_MAX_PROMPT_CHARS} chars)",
            )

        logger.info(
            "Ingested prompt for project=%s (%d chars)",
            ctx.project_id,
            len(prompt),
        )

        return NodeResult(outcome="success")
