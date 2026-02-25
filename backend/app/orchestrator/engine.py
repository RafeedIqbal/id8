"""Orchestrator engine — the main run loop for the ID8 state machine.

``run_orchestrator`` is the single entry point.  It loads a run from the
database, resolves the handler for the current node, executes it, and
advances through the transition table until it hits a wait node, a
terminal node, or an unrecoverable error.

Checkpointing is built-in: every transition writes ``current_node`` and
``updated_at`` to the database so the run can be resumed after a crash.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.orchestrator.base import NodeResult, RunContext
from app.orchestrator.handlers.registry import HANDLER_REGISTRY
from app.orchestrator.handlers.stubs import artifact_type_for_node
from app.orchestrator.nodes import NODE_REGISTRY, NODE_TO_PROJECT_STATUS, NodeName
from app.orchestrator.retry import RateLimitError, RetryableError, schedule_retry
from app.orchestrator.transitions import resolve_next_node

logger = logging.getLogger("id8.orchestrator.engine")


async def run_orchestrator(run_id: uuid.UUID, db: AsyncSession) -> None:
    """Drive *run_id* through the state machine until it parks or terminates.

    This function is safe to call multiple times for the same run — it is
    idempotent by design.
    """
    # Load run
    result = await db.execute(select(ProjectRun).where(ProjectRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        logger.error("Run %s not found — aborting", run_id)
        return

    logger.info("Orchestrator started for run=%s at node=%s", run_id, run.current_node)

    while True:
        node_name = run.current_node
        try:
            canonical_node = NodeName(node_name)
        except ValueError:
            logger.error("Unknown node '%s' for run=%s — marking failed", node_name, run_id)
            await _transition_to_failed(run, f"Unknown node: {node_name}", db)
            return
        meta = NODE_REGISTRY.get(canonical_node)

        if meta is None:
            logger.error("Unknown node '%s' for run=%s — marking failed", node_name, run_id)
            await _transition_to_failed(run, f"Unknown node: {node_name}", db)
            return

        # ---- Terminal node ------------------------------------------------
        if meta.is_terminal:
            await _handle_terminal(run, node_name, db)
            return

        # ---- Lookup handler -----------------------------------------------
        handler = HANDLER_REGISTRY.get(node_name)
        if handler is None:
            logger.error("No handler for node '%s' — marking failed", node_name)
            await _transition_to_failed(run, f"No handler for node: {node_name}", db)
            return

        # ---- Idempotency check: skip if artifact already exists -----------
        existing_artifact = await _check_existing_artifact(run_id, node_name, db)
        if meta.is_idempotent and existing_artifact is not None:
            logger.info("Artifact exists for run=%s node=%s — skipping", run_id, node_name)
            # Resolve next node using a "success"/"passed" outcome
            outcome = _default_outcome_for_skip(node_name)
            try:
                next_node = resolve_next_node(node_name, outcome)
            except Exception:
                logger.exception("Cannot resolve skip transition for node=%s", node_name)
                await _transition_to_failed(run, f"Skip transition failed for {node_name}", db)
                return
            await _advance(run, next_node, db)
            continue

        # ---- Execute handler ----------------------------------------------
        ctx = RunContext(
            run_id=run_id,
            project_id=run.project_id,
            current_node=node_name,
            attempt=run.retry_count,
            db_session=db,
            previous_artifacts=await _load_previous_artifacts(run_id, db),
        )

        try:
            node_result: NodeResult = await handler.execute(ctx)
        except RetryableError as exc:
            logger.warning("Retryable error in node=%s run=%s: %s", node_name, run_id, exc)
            await _handle_retryable_error(
                run,
                node_name,
                str(exc),
                db,
                use_fallback_profile=isinstance(exc, RateLimitError),
            )
            return
        except Exception as exc:
            logger.exception("Unhandled error in node=%s run=%s", node_name, run_id)
            await _transition_to_failed(run, f"{type(exc).__name__}: {exc}", db)
            return

        # ---- Wait node: park if still waiting -----------------------------
        if meta.is_wait_node and node_result.outcome == "waiting":
            logger.info("Run %s parked at wait node %s", run_id, node_name)
            await _update_project_status(run.project_id, node_name, db)
            return

        # ---- Persist artifact if handler produced one ---------------------
        if node_result.artifact_data is not None:
            await _persist_artifact(run, node_name, node_result.artifact_data, db)

        # ---- Resolve transition -------------------------------------------
        try:
            next_node = resolve_next_node(node_name, node_result.outcome)
        except Exception as exc:
            logger.error("Invalid transition node=%s outcome=%s: %s", node_name, node_result.outcome, exc)
            await _transition_to_failed(run, str(exc), db)
            return

        # Reset retry count on successful transition
        run.retry_count = 0
        await _advance(run, next_node, db)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _advance(run: ProjectRun, next_node: str, db: AsyncSession) -> None:
    """Move the run to *next_node* and sync project status."""
    run.current_node = next_node
    try:
        run.status = NODE_TO_PROJECT_STATUS[NodeName(next_node)]
    except (KeyError, ValueError):
        logger.warning("No run-status mapping for node=%s", next_node)
    run.updated_at = datetime.now(tz=UTC)
    run.last_error_code = None
    run.last_error_message = None
    await _update_project_status(run.project_id, next_node, db)
    await db.flush()
    logger.info("Run %s advanced to node=%s", run.id, next_node)


async def _handle_terminal(run: ProjectRun, node_name: str, db: AsyncSession) -> None:
    """Mark a run at a terminal node as complete."""
    terminal_status = NODE_TO_PROJECT_STATUS.get(NodeName(node_name), ProjectStatus.FAILED)
    run.status = terminal_status
    run.updated_at = datetime.now(tz=UTC)
    await _update_project_status(run.project_id, node_name, db)
    await db.flush()
    logger.info("Run %s reached terminal node=%s status=%s", run.id, node_name, terminal_status)


async def _transition_to_failed(run: ProjectRun, error_message: str, db: AsyncSession) -> None:
    """Transition the run to EndFailed with resume metadata."""
    run.current_node = NodeName.END_FAILED
    run.status = ProjectStatus.FAILED
    run.last_error_code = "ORCHESTRATOR_ERROR"
    run.last_error_message = error_message
    run.updated_at = datetime.now(tz=UTC)
    await _update_project_status(run.project_id, NodeName.END_FAILED, db)
    await db.flush()
    logger.error("Run %s failed: %s", run.id, error_message)


async def _handle_retryable_error(
    run: ProjectRun,
    node_name: str,
    error_message: str,
    db: AsyncSession,
    *,
    use_fallback_profile: bool,
) -> None:
    """Increment retry count and schedule a retry job, or fail if exhausted."""
    run.retry_count += 1
    run.last_error_code = "RATE_LIMIT" if use_fallback_profile else "RETRYABLE_ERROR"
    run.last_error_message = error_message
    run.updated_at = datetime.now(tz=UTC)

    job = await schedule_retry(
        run_id=run.id,
        node_name=node_name,
        retry_attempt=run.retry_count,
        error_message=error_message,
        use_fallback_profile=use_fallback_profile,
        db=db,
    )

    if job is None:
        # Retries exhausted
        await _transition_to_failed(run, f"Retry exhausted after {run.retry_count - 1} retries: {error_message}", db)
    else:
        await db.flush()


async def _update_project_status(
    project_id: uuid.UUID, node_name: str, db: AsyncSession
) -> None:
    """Set ``projects.status`` to match the current node."""
    try:
        target_status = NODE_TO_PROJECT_STATUS[NodeName(node_name)]
    except (ValueError, KeyError):
        logger.warning("No ProjectStatus mapping for node=%s", node_name)
        return

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is not None:
        project.status = target_status
        project.updated_at = datetime.now(tz=UTC)


async def _check_existing_artifact(
    run_id: uuid.UUID, node_name: str, db: AsyncSession
) -> ProjectArtifact | None:
    """Return an existing artifact for (run_id, node_name) if one exists."""
    a_type = artifact_type_for_node(node_name)
    if a_type is None:
        return None

    result = await db.execute(
        select(ProjectArtifact)
        .where(
            ProjectArtifact.run_id == run_id,
            ProjectArtifact.artifact_type == a_type,
            ProjectArtifact.content["__node_name"].astext == node_name,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _persist_artifact(
    run: ProjectRun,
    node_name: str,
    artifact_data: dict[str, Any],
    db: AsyncSession,
) -> None:
    """Create a new ``ProjectArtifact`` for the completed node."""
    a_type = artifact_type_for_node(node_name)
    if a_type is None:
        return

    # Compute next version
    version_result = await db.execute(
        select(func.coalesce(func.max(ProjectArtifact.version), 0)).where(
            ProjectArtifact.project_id == run.project_id,
            ProjectArtifact.artifact_type == a_type,
        )
    )
    next_version = version_result.scalar_one() + 1

    artifact = ProjectArtifact(
        project_id=run.project_id,
        run_id=run.id,
        artifact_type=a_type,
        version=next_version,
        content=_with_node_checkpoint(artifact_data, node_name),
    )
    db.add(artifact)
    await db.flush()
    logger.info("Persisted artifact type=%s version=%d for run=%s", a_type, next_version, run.id)


def _with_node_checkpoint(artifact_data: dict[str, Any], node_name: str) -> dict[str, Any]:
    content = dict(artifact_data)
    content["__node_name"] = node_name
    return content


async def _load_previous_artifacts(
    run_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, Any]:
    result = await db.execute(
        select(ProjectArtifact)
        .where(ProjectArtifact.run_id == run_id)
        .order_by(ProjectArtifact.created_at.desc())
    )
    artifacts: dict[str, Any] = {}
    for artifact in result.scalars():
        key = str(artifact.artifact_type)
        artifacts.setdefault(key, artifact.content)
    return artifacts


def _default_outcome_for_skip(node_name: str) -> str:
    """Return the default 'success' outcome key for a node when skipping."""
    # SecurityGate and DeployProduction use "passed" instead of "success"
    if node_name in (NodeName.SECURITY_GATE, NodeName.DEPLOY_PRODUCTION):
        return "passed"
    return "success"
