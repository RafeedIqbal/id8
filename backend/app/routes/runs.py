from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session, get_db
from app.dependencies.idempotency import get_idempotency_key
from app.models.approval_event import ApprovalEvent
from app.models.audit_event import AuditEvent
from app.models.enums import ApprovalStage, ArtifactType, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.observability import emit_audit_event
from app.orchestrator import ALL_NODE_NAMES, NODE_TO_PROJECT_STATUS, NodeName, run_orchestrator
from app.orchestrator.handlers.stubs import artifact_type_for_node
from app.schemas.run import (
    CreateRunRequest,
    ProjectRunDetailResponse,
    ProjectRunResponse,
    ReplayMode,
    RunTimelineEvent,
)

router = APIRouter(tags=["runs"])
logger = logging.getLogger(__name__)

_NODE_PROGRESS_ORDER: tuple[NodeName, ...] = (
    NodeName.INGEST_PROMPT,
    NodeName.GENERATE_PRD,
    NodeName.WAIT_PRD_APPROVAL,
    NodeName.GENERATE_DESIGN,
    NodeName.WAIT_DESIGN_APPROVAL,
    NodeName.GENERATE_TECH_PLAN,
    NodeName.WAIT_TECH_PLAN_APPROVAL,
    NodeName.WRITE_CODE,
    NodeName.SECURITY_GATE,
    NodeName.PREPARE_PR,
    NodeName.WAIT_DEPLOY_APPROVAL,
    NodeName.DEPLOY_PRODUCTION,
    NodeName.END_SUCCESS,
    NodeName.END_FAILED,
)
_NODE_PROGRESS_INDEX: dict[NodeName, int] = {node: idx for idx, node in enumerate(_NODE_PROGRESS_ORDER)}
_WAIT_NODE_TO_STAGE: dict[NodeName, ApprovalStage] = {
    NodeName.WAIT_PRD_APPROVAL: ApprovalStage.PRD,
    NodeName.WAIT_DESIGN_APPROVAL: ApprovalStage.DESIGN,
    NodeName.WAIT_TECH_PLAN_APPROVAL: ApprovalStage.TECH_PLAN,
    NodeName.WAIT_DEPLOY_APPROVAL: ApprovalStage.DEPLOY,
}
_TIMELINE_EVENT_TYPES = (
    "orchestrator.run_started",
    "orchestrator.run_resumed",
    "orchestrator.run_replayed",
    "orchestrator.node_transition",
    "orchestrator.run_failed",
    "orchestrator.run_requeued",
)

_TERMINAL_RUN_STATUSES = {ProjectStatus.DEPLOYED, ProjectStatus.FAILED}
_TERMINAL_RUN_NODES = {NodeName.END_SUCCESS, NodeName.END_FAILED}


async def _run_orchestrator_background(run_id: uuid.UUID) -> None:
    """Fire-and-forget wrapper that opens its own DB session."""
    async with async_session() as db:
        try:
            await run_orchestrator(run_id, db)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Background orchestrator run failed for run_id=%s", run_id)


async def _latest_run_for_project(project_id: uuid.UUID, db: AsyncSession) -> ProjectRun | None:
    result = await db.execute(
        select(ProjectRun)
        .where(ProjectRun.project_id == project_id)
        .order_by(ProjectRun.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _record_run_event(
    *,
    db: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    event_type: str,
    to_node: str | NodeName,
    from_node: str | NodeName | None = None,
    outcome: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "run_id": str(run_id),
        "to_node": str(to_node),
    }
    if from_node is not None:
        payload["from_node"] = str(from_node)
    if outcome:
        payload["outcome"] = outcome

    await emit_audit_event(
        project_id,
        None,
        event_type,
        payload,
        db,
    )


async def _load_timeline_events(
    *,
    db: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
) -> list[RunTimelineEvent]:
    result = await db.execute(
        select(AuditEvent)
        .where(
            AuditEvent.project_id == project_id,
            AuditEvent.event_payload["run_id"].astext == str(run_id),
            AuditEvent.event_type.in_(_TIMELINE_EVENT_TYPES),
        )
        .order_by(AuditEvent.created_at.asc())
    )
    events: list[RunTimelineEvent] = []
    for record in result.scalars():
        payload = record.event_payload if isinstance(record.event_payload, dict) else {}
        to_node = payload.get("to_node")
        if not isinstance(to_node, str) or not to_node:
            continue

        raw_from_node = payload.get("from_node")
        raw_outcome = payload.get("outcome")
        events.append(
            RunTimelineEvent(
                event_type=record.event_type,
                from_node=raw_from_node if isinstance(raw_from_node, str) else None,
                to_node=to_node,
                outcome=raw_outcome if isinstance(raw_outcome, str) else None,
                created_at=record.created_at,
            )
        )
    return events


async def _was_node_previously_reached(
    previous_run: ProjectRun,
    resume_node: NodeName,
    db: AsyncSession,
) -> bool:
    if resume_node == NodeName.INGEST_PROMPT:
        return True

    if previous_run.current_node == resume_node:
        return True

    try:
        previous_node = NodeName(previous_run.current_node)
    except ValueError:
        previous_node = None

    if previous_node == NodeName.END_SUCCESS:
        return True

    if previous_node not in {None, NodeName.END_FAILED}:
        try:
            previous_idx = _NODE_PROGRESS_INDEX[previous_node]
            target_idx = _NODE_PROGRESS_INDEX[resume_node]
        except KeyError:
            previous_idx = -1
            target_idx = -1
        if previous_idx >= 0 and target_idx >= 0 and previous_idx >= target_idx:
            return True

    # If the run has already reached EndFailed, infer node reachability from
    # audit events as a durable source of execution history.
    audit_result = await db.execute(
        select(AuditEvent.id)
        .where(
            AuditEvent.event_payload["run_id"].astext == str(previous_run.id),
            or_(
                AuditEvent.event_payload["node"].astext == str(resume_node),
                AuditEvent.event_payload["to_node"].astext == str(resume_node),
                AuditEvent.event_payload["from_node"].astext == str(resume_node),
            ),
        )
        .limit(1)
    )
    if audit_result.scalar_one_or_none() is not None:
        return True

    artifact_type = artifact_type_for_node(resume_node)
    if artifact_type is not None:
        artifact_result = await db.execute(
            select(ProjectArtifact.id)
            .where(
                ProjectArtifact.run_id == previous_run.id,
                ProjectArtifact.artifact_type == artifact_type,
            )
            .limit(1)
        )
        if artifact_result.scalar_one_or_none() is not None:
            return True

    stage = _WAIT_NODE_TO_STAGE.get(resume_node)
    if stage is not None:
        approval_result = await db.execute(
            select(ApprovalEvent.id)
            .where(
                ApprovalEvent.run_id == previous_run.id,
                ApprovalEvent.stage == stage,
            )
            .limit(1)
        )
        if approval_result.scalar_one_or_none() is not None:
            return True

    return False


async def _copy_artifacts_before_node(
    *,
    db: AsyncSession,
    source_run_id: uuid.UUID,
    new_run_id: uuid.UUID,
    project_id: uuid.UUID,
    target_node: NodeName,
) -> None:
    """Copy artifacts from nodes before target_node into the new run."""
    target_idx = _NODE_PROGRESS_INDEX.get(target_node, 0)

    # Collect artifact types for nodes before the target
    prior_artifact_types = set()
    for node, idx in _NODE_PROGRESS_INDEX.items():
        if idx < target_idx:
            at = artifact_type_for_node(node)
            if at is not None:
                prior_artifact_types.add(at)

    if not prior_artifact_types:
        return

    result = await db.execute(
        select(ProjectArtifact)
        .where(
            ProjectArtifact.run_id == source_run_id,
            ProjectArtifact.artifact_type.in_(prior_artifact_types),
        )
        .order_by(ProjectArtifact.artifact_type.asc(), ProjectArtifact.version.asc())
    )
    source_artifacts = list(result.scalars().all())

    if not source_artifacts:
        return

    # Rebase versions to avoid violating unique (project_id, artifact_type, version).
    max_version_rows = await db.execute(
        select(
            ProjectArtifact.artifact_type,
            func.max(ProjectArtifact.version).label("max_version"),
        )
        .where(
            ProjectArtifact.project_id == project_id,
            ProjectArtifact.artifact_type.in_(prior_artifact_types),
        )
        .group_by(ProjectArtifact.artifact_type)
    )
    next_version_by_type: dict[ArtifactType, int] = {}
    for row in max_version_rows:
        next_version_by_type[row.artifact_type] = int(row.max_version or 0) + 1

    for art in source_artifacts:
        next_version = next_version_by_type.get(art.artifact_type, 1)
        next_version_by_type[art.artifact_type] = next_version + 1
        new_artifact = ProjectArtifact(
            project_id=project_id,
            run_id=new_run_id,
            artifact_type=art.artifact_type,
            version=next_version,
            content=art.content,
            model_profile=art.model_profile,
        )
        db.add(new_artifact)


def _is_run_terminal(run: ProjectRun) -> bool:
    """Check if a run is in a terminal state."""
    try:
        node = NodeName(run.current_node)
    except ValueError:
        node = None
    return (
        run.status in _TERMINAL_RUN_STATUSES
        or node in _TERMINAL_RUN_NODES
    )


@router.get(
    "/projects/{projectId}/runs/latest",
    operation_id="getLatestRun",
    response_model=ProjectRunDetailResponse,
)
async def get_latest_run(
    project_id: uuid.UUID = Path(alias="projectId"),
    db: AsyncSession = Depends(get_db),
) -> ProjectRunDetailResponse:
    result = await db.execute(
        select(Project.id).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    run = await _latest_run_for_project(project_id, db)
    if run is None:
        raise HTTPException(status_code=404, detail="No runs found for this project")

    timeline = await _load_timeline_events(db=db, project_id=project_id, run_id=run.id)
    if not timeline:
        timeline = [
            RunTimelineEvent(
                event_type="orchestrator.run_started",
                to_node=str(run.current_node),
                outcome="started",
                created_at=run.created_at,
            )
        ]

    payload = ProjectRunResponse.model_validate(run).model_dump()
    payload["timeline"] = [event.model_dump() for event in timeline]
    return ProjectRunDetailResponse.model_validate(payload)


@router.post("/projects/{projectId}/runs", operation_id="createRun", response_model=ProjectRunResponse, status_code=202)
async def create_run(
    background_tasks: BackgroundTasks,
    project_id: uuid.UUID = Path(alias="projectId"),
    body: CreateRunRequest | None = None,
    idempotency_key: str | None = Depends(get_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> ProjectRun:
    # Check project exists
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Determine replay mode
    replay_mode = body.replay_mode if body else None
    resume_from_node = body.resume_from_node if body else None

    if replay_mode is not None and not resume_from_node:
        raise HTTPException(
            status_code=422,
            detail="resume_from_node is required when replay_mode is provided",
        )

    if resume_from_node and replay_mode is None:
        previous_run = await _latest_run_for_project(project_id, db)
        if previous_run is not None and _is_run_terminal(previous_run):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Terminal runs require explicit replay_mode: "
                    "retry_failed or replay_from_node"
                ),
            )

    # ── replay_from_node: Create NEW run at target node ──────────────────
    if replay_mode == ReplayMode.REPLAY_FROM_NODE and resume_from_node:
        if resume_from_node not in ALL_NODE_NAMES:
            raise HTTPException(status_code=422, detail=f"Unknown node: {resume_from_node}")

        target_node = NodeName(resume_from_node)
        previous_run = await _latest_run_for_project(project_id, db)
        if previous_run is None:
            raise HTTPException(status_code=409, detail="No prior run exists to replay from")
        if not _is_run_terminal(previous_run):
            raise HTTPException(status_code=409, detail="replay_from_node requires a terminal run")
        if not await _was_node_previously_reached(previous_run, target_node, db):
            raise HTTPException(
                status_code=409,
                detail=f"Node {target_node} was not reached by the previous run",
            )

        new_run = ProjectRun(
            project_id=project_id,
            status=NODE_TO_PROJECT_STATUS[target_node],
            current_node=target_node,
            idempotency_key=idempotency_key,
        )
        db.add(new_run)
        await db.flush()

        # Copy artifacts from nodes before target
        await _copy_artifacts_before_node(
            db=db,
            source_run_id=previous_run.id,
            new_run_id=new_run.id,
            project_id=project_id,
            target_node=target_node,
        )

        project.status = NODE_TO_PROJECT_STATUS[target_node]
        project.updated_at = datetime.now(tz=UTC)

        await _record_run_event(
            db=db,
            project_id=project_id,
            run_id=new_run.id,
            event_type="orchestrator.run_replayed",
            from_node=previous_run.current_node,
            to_node=target_node,
            outcome="replayed",
        )
        await db.commit()
        await db.refresh(new_run)
        background_tasks.add_task(_run_orchestrator_background, new_run.id)
        return new_run

    # ── retry_failed (existing behavior): Mutate existing run ────────────
    if resume_from_node:
        if resume_from_node not in ALL_NODE_NAMES:
            raise HTTPException(status_code=422, detail=f"Unknown node: {resume_from_node}")

        resume_node = NodeName(resume_from_node)
        previous_run = await _latest_run_for_project(project_id, db)
        if previous_run is None:
            raise HTTPException(status_code=409, detail="No prior run exists to resume from")
        if previous_run.status != ProjectStatus.FAILED and previous_run.current_node != NodeName.END_FAILED:
            raise HTTPException(status_code=409, detail="resume_from_node is only valid for a failed run")
        if not await _was_node_previously_reached(previous_run, resume_node, db):
            raise HTTPException(
                status_code=409,
                detail=f"Node {resume_node} was not reached by the failed run",
            )

        from_node = previous_run.current_node
        previous_run.current_node = resume_node
        previous_run.status = NODE_TO_PROJECT_STATUS[resume_node]
        previous_run.retry_count = 0
        previous_run.last_error_code = None
        previous_run.last_error_message = None
        previous_run.updated_at = datetime.now(tz=UTC)
        project.status = NODE_TO_PROJECT_STATUS[resume_node]
        project.updated_at = datetime.now(tz=UTC)
        await _record_run_event(
            db=db,
            project_id=project_id,
            run_id=previous_run.id,
            event_type="run.started",
            from_node=from_node,
            to_node=resume_node,
            outcome="resumed",
        )
        await _record_run_event(
            db=db,
            project_id=project_id,
            run_id=previous_run.id,
            event_type="orchestrator.run_resumed",
            from_node=from_node,
            to_node=resume_node,
            outcome="resumed",
        )
        await db.commit()
        await db.refresh(previous_run)
        background_tasks.add_task(_run_orchestrator_background, previous_run.id)
        return previous_run

    # ── Fresh run ────────────────────────────────────────────────────────
    # Idempotency: return existing run if key matches
    if idempotency_key:
        run_result = await db.execute(
            select(ProjectRun).where(
                ProjectRun.project_id == project_id,
                ProjectRun.idempotency_key == idempotency_key,
            )
        )
        existing_run = run_result.scalar_one_or_none()
        if existing_run is not None:
            return existing_run

        key_result = await db.execute(select(ProjectRun).where(ProjectRun.idempotency_key == idempotency_key))
        existing_other_project_run = key_result.scalar_one_or_none()
        if existing_other_project_run is not None:
            raise HTTPException(status_code=409, detail="Idempotency-Key already used for a different project")

    start_node = NodeName.INGEST_PROMPT

    run = ProjectRun(
        project_id=project_id,
        status=NODE_TO_PROJECT_STATUS[start_node],
        current_node=start_node,
        idempotency_key=idempotency_key,
    )
    db.add(run)
    try:
        await db.flush()
        await _record_run_event(
            db=db,
            project_id=project_id,
            run_id=run.id,
            event_type="run.started",
            to_node=start_node,
            outcome="started",
        )
        await _record_run_event(
            db=db,
            project_id=project_id,
            run_id=run.id,
            event_type="orchestrator.run_started",
            to_node=start_node,
            outcome="started",
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if not idempotency_key:
            raise exc

        existing_result = await db.execute(select(ProjectRun).where(ProjectRun.idempotency_key == idempotency_key))
        existing_run = existing_result.scalar_one_or_none()
        if existing_run and existing_run.project_id == project_id:
            return existing_run
        raise HTTPException(status_code=409, detail="Idempotency-Key already used for a different project") from exc
    await db.refresh(run)

    # Enqueue orchestrator processing as a background task
    background_tasks.add_task(_run_orchestrator_background, run.id)

    return run
