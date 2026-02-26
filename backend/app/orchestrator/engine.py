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
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent
from app.models.enums import ModelProfile, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.observability import (
    NODE_P95_TARGET_MS,
    PIPELINE_P95_TARGET_MS,
    categorize_failure_reason,
    emit_audit_event,
)
from app.observability.costs import estimate_llm_cost_usd
from app.orchestrator.base import NodeResult, RunContext
from app.orchestrator.handlers.registry import HANDLER_REGISTRY
from app.orchestrator.handlers.stubs import artifact_type_for_node
from app.orchestrator.nodes import NODE_REGISTRY, NODE_TO_PROJECT_STATUS, NodeName
from app.orchestrator.retry import RateLimitError, RetryableError, schedule_retry
from app.orchestrator.transitions import resolve_next_node

if TYPE_CHECKING:
    from app.llm.client import LlmResponse

logger = logging.getLogger("id8.orchestrator.engine")


async def run_orchestrator(run_id: uuid.UUID, db: AsyncSession) -> None:
    """Drive *run_id* through the state machine until it parks or terminates.

    This function is safe to call multiple times for the same run — it is
    idempotent by design.
    """
    result = await db.execute(select(ProjectRun.id).where(ProjectRun.id == run_id))
    if result.scalar_one_or_none() is None:
        logger.error("Run %s not found — aborting", run_id)
        return

    logger.info("Orchestrator started for run=%s", run_id)
    workflow_payload: dict[str, Any] = {}

    while True:
        run = await _lock_run_for_processing(run_id, db)
        if run is None:
            logger.info("Run %s is already being processed by another worker", run_id)
            return

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
            await emit_audit_event(
                run.project_id,
                None,
                "run.node_completed",
                {
                    "run_id": str(run.id),
                    "node": node_name,
                    "attempt": run.retry_count + 1,
                    "duration_ms": 0.0,
                    "outcome": "skipped",
                    "skipped": True,
                },
                db,
            )
            # Resolve next node using a "success"/"passed" outcome
            outcome = _default_outcome_for_skip(node_name)
            try:
                next_node = resolve_next_node(node_name, outcome)
            except Exception:
                logger.exception("Cannot resolve skip transition for node=%s", node_name)
                await _transition_to_failed(run, f"Skip transition failed for {node_name}", db)
                return
            await _advance(run, next_node, db, outcome=outcome)
            continue

        # ---- Execute handler ----------------------------------------------
        previous_artifacts = await _load_previous_artifacts(run_id, run.project_id, db)
        ctx = RunContext(
            run_id=run_id,
            project_id=run.project_id,
            current_node=node_name,
            attempt=run.retry_count,
            db_session=db,
            previous_artifacts=previous_artifacts,
            workflow_payload=dict(workflow_payload),
        )

        await emit_audit_event(
            run.project_id,
            None,
            "run.node_entered",
            {
                "run_id": str(run.id),
                "node": node_name,
                "attempt": run.retry_count + 1,
            },
            db,
        )
        node_start = time.monotonic()
        try:
            node_result: NodeResult = await handler.execute(ctx)
        except RetryableError as exc:
            duration_ms = round((time.monotonic() - node_start) * 1000, 2)
            _warn_if_node_exceeds_slo(node_name, duration_ms, run_id)
            logger.warning("Retryable error in node=%s run=%s: %s", node_name, run_id, exc)
            await _handle_retryable_error(
                run,
                node_name,
                str(exc),
                db,
                use_fallback_profile=isinstance(exc, RateLimitError),
                minimum_delay_seconds=getattr(exc, "retry_after_seconds", None),
                node_duration_ms=duration_ms,
            )
            return
        except Exception as exc:
            duration_ms = round((time.monotonic() - node_start) * 1000, 2)
            _warn_if_node_exceeds_slo(node_name, duration_ms, run_id)
            await emit_audit_event(
                run.project_id,
                None,
                "run.node_completed",
                {
                    "run_id": str(run.id),
                    "node": node_name,
                    "attempt": run.retry_count + 1,
                    "duration_ms": duration_ms,
                    "outcome": "failure",
                    "error": f"{type(exc).__name__}: {exc}",
                    "failure_reason": categorize_failure_reason(
                        error_message=f"{type(exc).__name__}: {exc}",
                    ),
                },
                db,
            )
            logger.exception("Unhandled error in node=%s run=%s", node_name, run_id)
            await _transition_to_failed(run, f"{type(exc).__name__}: {exc}", db)
            return

        duration_ms = round((time.monotonic() - node_start) * 1000, 2)
        _warn_if_node_exceeds_slo(node_name, duration_ms, run_id)

        # ---- Wait node: park if still waiting -----------------------------
        if meta.is_wait_node and node_result.outcome == "waiting":
            await emit_audit_event(
                run.project_id,
                None,
                "run.node_completed",
                {
                    "run_id": str(run.id),
                    "node": node_name,
                    "attempt": run.retry_count + 1,
                    "duration_ms": duration_ms,
                    "outcome": "waiting",
                },
                db,
            )
            logger.info("Run %s parked at wait node %s", run_id, node_name)
            await _update_project_status(run.project_id, node_name, db)
            return

        if node_result.context_updates:
            workflow_payload.update(node_result.context_updates)

        # ---- Persist artifact if handler produced one ---------------------
        if node_result.artifact_data is not None:
            await _persist_artifact(
                run,
                node_name,
                node_result.artifact_data,
                db,
                llm_response=node_result.llm_response,
            )

        # ---- Resolve transition -------------------------------------------
        try:
            next_node = resolve_next_node(node_name, node_result.outcome)
        except Exception as exc:
            await emit_audit_event(
                run.project_id,
                None,
                "run.node_completed",
                {
                    "run_id": str(run.id),
                    "node": node_name,
                    "attempt": run.retry_count + 1,
                    "duration_ms": duration_ms,
                    "outcome": "failure",
                    "error": str(exc),
                    "failure_reason": categorize_failure_reason(error_message=str(exc)),
                },
                db,
            )
            logger.error("Invalid transition node=%s outcome=%s: %s", node_name, node_result.outcome, exc)
            await _transition_to_failed(run, str(exc), db)
            return

        completed_payload: dict[str, Any] = {
            "run_id": str(run.id),
            "node": node_name,
            "attempt": run.retry_count + 1,
            "duration_ms": duration_ms,
            "outcome": node_result.outcome,
            "next_node": str(next_node),
        }
        if node_result.error:
            completed_payload["error"] = node_result.error
            completed_payload["failure_reason"] = categorize_failure_reason(error_message=node_result.error)
        elif node_result.outcome in {"failure", "failed"}:
            completed_payload["failure_reason"] = categorize_failure_reason(error_message=None)

        await emit_audit_event(
            run.project_id,
            None,
            "run.node_completed",
            completed_payload,
            db,
        )

        # Reset retry count on successful transition
        run.retry_count = 0
        await _advance(run, next_node, db, outcome=node_result.outcome)

        # Wait nodes are explicit HITL pause points. Park immediately after
        # entering one so a single approval/rejection event is not reprocessed
        # multiple times in the same orchestrator invocation.
        try:
            next_meta = NODE_REGISTRY[NodeName(next_node)]
        except (KeyError, ValueError):
            next_meta = None
        if next_meta is not None and next_meta.is_wait_node:
            logger.info("Run %s parked after entering wait node %s", run_id, next_node)
            return


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _advance(
    run: ProjectRun,
    next_node: str,
    db: AsyncSession,
    *,
    outcome: str | None = None,
) -> None:
    """Move the run to *next_node* and sync project status."""
    from_node = run.current_node
    run.current_node = next_node
    try:
        run.status = NODE_TO_PROJECT_STATUS[NodeName(next_node)]
    except (KeyError, ValueError):
        logger.warning("No run-status mapping for node=%s", next_node)
    run.updated_at = datetime.now(tz=UTC)
    run.last_error_code = None
    run.last_error_message = None
    await _update_project_status(run.project_id, next_node, db)
    await _record_run_event(
        db=db,
        project_id=run.project_id,
        run_id=run.id,
        event_type="orchestrator.node_transition",
        from_node=from_node,
        to_node=next_node,
        outcome=outcome,
    )
    # Commit each node transition as a checkpoint so external readers
    # (API/UI/worker recovery) observe forward progress immediately.
    await db.commit()
    logger.info("Run %s advanced to node=%s", run.id, next_node)


async def _handle_terminal(run: ProjectRun, node_name: str, db: AsyncSession) -> None:
    """Mark a run at a terminal node as complete."""
    finished_at = datetime.now(tz=UTC)
    terminal_status = NODE_TO_PROJECT_STATUS.get(NodeName(node_name), ProjectStatus.FAILED)
    run.status = terminal_status
    run.updated_at = finished_at
    await _update_project_status(run.project_id, node_name, db)

    total_duration_ms = round((finished_at - run.created_at).total_seconds() * 1000, 2)
    if node_name == NodeName.END_SUCCESS:
        await emit_audit_event(
            run.project_id,
            None,
            "run.completed",
            {
                "run_id": str(run.id),
                "node": node_name,
                "total_duration_ms": total_duration_ms,
                "status": str(terminal_status),
            },
            db,
        )
        if total_duration_ms > PIPELINE_P95_TARGET_MS:
            logger.warning(
                "SLO warning run=%s end_to_end_duration_ms=%.2f exceeds p95 target %.2f",
                run.id,
                total_duration_ms,
                PIPELINE_P95_TARGET_MS,
            )
    elif node_name == NodeName.END_FAILED:
        failure_reason = categorize_failure_reason(
            error_message=run.last_error_message,
            error_code=run.last_error_code,
        )
        await emit_audit_event(
            run.project_id,
            None,
            "run.failed",
            {
                "run_id": str(run.id),
                "from_node": node_name,
                "to_node": str(NodeName.END_FAILED),
                "error": run.last_error_message or "Run reached EndFailed",
                "failure_reason": failure_reason,
                "retry_count": run.retry_count,
                "total_duration_ms": total_duration_ms,
            },
            db,
        )
        await _record_run_event(
            db=db,
            project_id=run.project_id,
            run_id=run.id,
            event_type="orchestrator.run_failed",
            from_node=node_name,
            to_node=NodeName.END_FAILED,
            outcome="failure",
            error=run.last_error_message,
        )
    await db.flush()
    logger.info("Run %s reached terminal node=%s status=%s", run.id, node_name, terminal_status)


async def _transition_to_failed(run: ProjectRun, error_message: str, db: AsyncSession) -> None:
    """Transition the run to EndFailed with resume metadata."""
    from_node = run.current_node
    run.current_node = NodeName.END_FAILED
    run.status = ProjectStatus.FAILED
    if not run.last_error_code:
        run.last_error_code = "ORCHESTRATOR_ERROR"
    run.last_error_message = error_message
    now = datetime.now(tz=UTC)
    run.updated_at = now
    await _update_project_status(run.project_id, NodeName.END_FAILED, db)
    await _record_run_event(
        db=db,
        project_id=run.project_id,
        run_id=run.id,
        event_type="orchestrator.run_failed",
        from_node=from_node,
        to_node=NodeName.END_FAILED,
        outcome="failure",
        error=error_message,
    )
    await emit_audit_event(
        run.project_id,
        None,
        "run.failed",
        {
            "run_id": str(run.id),
            "from_node": str(from_node),
            "to_node": str(NodeName.END_FAILED),
            "error": error_message,
            "failure_reason": categorize_failure_reason(
                error_message=error_message,
                error_code=run.last_error_code,
            ),
            "retry_count": run.retry_count,
            "total_duration_ms": round((now - run.created_at).total_seconds() * 1000, 2),
        },
        db,
    )
    await db.flush()
    logger.error("Run %s failed: %s", run.id, error_message)


async def _handle_retryable_error(
    run: ProjectRun,
    node_name: str,
    error_message: str,
    db: AsyncSession,
    *,
    use_fallback_profile: bool,
    minimum_delay_seconds: float | None,
    node_duration_ms: float,
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
        minimum_delay_seconds=minimum_delay_seconds,
        db=db,
    )

    if job is None:
        # Retries exhausted
        await _transition_to_failed(run, f"Retry exhausted after {run.retry_count - 1} retries: {error_message}", db)
    else:
        payload = job.payload if isinstance(job.payload, dict) else {}
        retry_delay_ms = round(float(payload.get("delay_seconds", 0.0)) * 1000, 2)
        if retry_delay_ms <= 0:
            retry_delay_ms = round(max((job.scheduled_for - run.updated_at).total_seconds() * 1000, 0.0), 2)
        failure_reason = categorize_failure_reason(
            error_message=error_message,
            error_code=run.last_error_code,
        )
        await emit_audit_event(
            run.project_id,
            None,
            "run.retry_scheduled",
            {
                "run_id": str(run.id),
                "node": node_name,
                "retry_attempt": run.retry_count,
                "retry_delay_ms": retry_delay_ms,
                "failure_reason": failure_reason,
                "error": error_message,
            },
            db,
        )
        await emit_audit_event(
            run.project_id,
            None,
            "run.node_completed",
            {
                "run_id": str(run.id),
                "node": node_name,
                "attempt": run.retry_count,
                "duration_ms": node_duration_ms,
                "outcome": "retry_scheduled",
                "retry_attempt": run.retry_count,
                "retry_delay_ms": retry_delay_ms,
                "error": error_message,
                "failure_reason": failure_reason,
            },
            db,
        )
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


async def _lock_run_for_processing(
    run_id: uuid.UUID,
    db: AsyncSession,
) -> ProjectRun | None:
    """Lock and return ``ProjectRun`` for one-node-at-a-time execution.

    PostgreSQL uses ``FOR UPDATE SKIP LOCKED`` so concurrent orchestrators
    return ``None`` immediately instead of racing the same run.
    """
    stmt = select(ProjectRun).where(ProjectRun.id == run_id)
    bind = db.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""
    if dialect_name != "sqlite":
        stmt = stmt.with_for_update(skip_locked=True)

    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _check_existing_artifact(
    run_id: uuid.UUID, node_name: str, db: AsyncSession
) -> ProjectArtifact | None:
    """Return an existing *successful* checkpoint artifact for (run_id, node_name).

    For DeployProduction we only treat an artifact as reusable when it
    represents a successful deployment. Failed deploy artifacts must not skip
    the node because operators need to retry real deployment work.
    """
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
    artifact = result.scalar_one_or_none()
    if artifact is None:
        return None

    if not _is_reusable_checkpoint_artifact(node_name, artifact.content):
        logger.info(
            "Ignoring non-reusable checkpoint for run=%s node=%s artifact=%s",
            run_id,
            node_name,
            artifact.id,
        )
        return None

    return artifact


def _is_reusable_checkpoint_artifact(node_name: str, content: Any) -> bool:
    """Whether *content* is safe to use as an idempotent checkpoint.

    Most nodes treat any matching artifact as reusable. DeployProduction is
    stricter: only successful deploy reports (no error + live_url present)
    can skip re-execution.
    """
    if node_name != str(NodeName.DEPLOY_PRODUCTION):
        return True

    if not isinstance(content, dict):
        return False

    if content.get("error"):
        return False

    live_url = content.get("live_url")
    if not isinstance(live_url, str) or not live_url.strip():
        return False

    return True


async def _persist_artifact(
    run: ProjectRun,
    node_name: str,
    artifact_data: dict[str, Any],
    db: AsyncSession,
    *,
    llm_response: LlmResponse | None = None,
) -> None:
    """Create a new ``ProjectArtifact`` for the completed node.

    When *llm_response* is provided the artifact records the model
    profile and token-usage telemetry.
    """
    a_type = artifact_type_for_node(node_name)
    if a_type is None:
        return

    # Build content with optional LLM metadata
    content = _with_node_checkpoint(artifact_data, node_name)
    model_profile: ModelProfile | None = None
    if llm_response is not None:
        model_profile = llm_response.profile_used
        estimated_cost_usd = estimate_llm_cost_usd(
            model_id=llm_response.model_id,
            prompt_tokens=llm_response.token_usage.prompt_tokens,
            completion_tokens=llm_response.token_usage.completion_tokens,
        )
        content["__llm_metadata"] = {
            "model_id": llm_response.model_id,
            "model_profile": str(llm_response.profile_used),
            "prompt_tokens": llm_response.token_usage.prompt_tokens,
            "completion_tokens": llm_response.token_usage.completion_tokens,
            "latency_ms": llm_response.latency_ms,
            "estimated_cost_usd": estimated_cost_usd,
        }

    pending_artifact = await _pending_artifact_for_run(run.id, a_type, db)
    if pending_artifact is not None:
        if model_profile is None:
            model_profile = pending_artifact.model_profile
        pending_artifact.content = content
        pending_artifact.model_profile = model_profile
        await db.flush()
        logger.info(
            "Updated pending artifact type=%s version=%d for run=%s",
            a_type,
            pending_artifact.version,
            run.id,
        )
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
        content=content,
        model_profile=model_profile,
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
    project_id: uuid.UUID,
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

    selected_ids = await _selected_artifact_ids_for_run(project_id, run_id, db)
    if selected_ids:
        selected_result = await db.execute(
            select(ProjectArtifact).where(ProjectArtifact.id.in_(set(selected_ids.values())))
        )
        selected_by_id = {artifact.id: artifact for artifact in selected_result.scalars()}
        for artifact_key, artifact_id in selected_ids.items():
            selected_artifact = selected_by_id.get(artifact_id)
            if selected_artifact is not None:
                artifacts[artifact_key] = selected_artifact.content

    return artifacts


async def _pending_artifact_for_run(
    run_id: uuid.UUID,
    artifact_type: Any,
    db: AsyncSession,
) -> ProjectArtifact | None:
    result = await db.execute(
        select(ProjectArtifact)
        .where(
            ProjectArtifact.run_id == run_id,
            ProjectArtifact.artifact_type == artifact_type,
            ProjectArtifact.content["status"].astext == "pending",
        )
        .order_by(ProjectArtifact.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _artifact_key_for_stage(stage: str) -> str | None:
    mapping = {
        "prd": "prd",
        "design": "design_spec",
        "tech_plan": "tech_plan",
        "deploy": "code_snapshot",
    }
    return mapping.get(stage.strip().lower())


async def _selected_artifact_ids_for_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, uuid.UUID]:
    result = await db.execute(
        select(AuditEvent)
        .where(
            AuditEvent.project_id == project_id,
            AuditEvent.event_type == "approval.submitted",
            AuditEvent.event_payload["run_id"].astext == str(run_id),
            AuditEvent.event_payload["decision"].astext == "approved",
        )
        .order_by(AuditEvent.created_at.desc())
    )

    selected: dict[str, uuid.UUID] = {}
    for event in result.scalars():
        payload = event.event_payload if isinstance(event.event_payload, dict) else {}
        stage_raw = payload.get("stage")
        artifact_raw = payload.get("artifact_id")
        if not isinstance(stage_raw, str) or not isinstance(artifact_raw, str):
            continue
        artifact_key = _artifact_key_for_stage(stage_raw)
        if artifact_key is None or artifact_key in selected:
            continue
        try:
            selected[artifact_key] = uuid.UUID(artifact_raw)
        except ValueError:
            continue
    return selected


def _default_outcome_for_skip(node_name: str) -> str:
    """Return the default 'success' outcome key for a node when skipping."""
    # SecurityGate and DeployProduction use "passed" instead of "success"
    if node_name in (str(NodeName.SECURITY_GATE), str(NodeName.DEPLOY_PRODUCTION)):
        return "passed"
    return "success"


async def _record_run_event(
    *,
    db: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    event_type: str,
    to_node: str | NodeName,
    from_node: str | NodeName | None = None,
    outcome: str | None = None,
    error: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "run_id": str(run_id),
        "to_node": str(to_node),
    }
    if from_node is not None:
        payload["from_node"] = str(from_node)
    if outcome:
        payload["outcome"] = outcome
    if error:
        payload["error"] = error

    await emit_audit_event(
        project_id,
        None,
        event_type,
        payload,
        db,
    )


def _warn_if_node_exceeds_slo(node_name: str, duration_ms: float, run_id: uuid.UUID) -> None:
    target_ms = NODE_P95_TARGET_MS.get(node_name)
    if target_ms is None:
        return
    if duration_ms <= target_ms:
        return
    logger.warning(
        "SLO warning run=%s node=%s duration_ms=%.2f exceeds p95 target %.2f",
        run_id,
        node_name,
        duration_ms,
        target_ms,
    )
