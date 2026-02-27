from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.audit_event import AuditEvent
from app.models.project import Project
from app.models.project_run import ProjectRun
from app.models.user import User
from app.observability import emit_audit_event, summarize_distribution
from app.schemas.metrics import (
    DeploymentMetric,
    DistributionMetric,
    FailureReasonMetric,
    NodeLatencyMetric,
    ProfileTokenCostMetric,
    ProjectMetricsResponse,
    RetryMetric,
    RunTokenCostMetric,
    StageSloMetric,
    TokenCostTotals,
)
from app.schemas.project import (
    CreateProjectRequest,
    DeleteProjectResponse,
    ProjectListItem,
    ProjectListResponse,
    ProjectResponse,
    UpdateProjectRequest,
)
from app.schemas.stack import DEFAULT_STACK

router = APIRouter(tags=["projects"])
_SCAFFOLD_OWNER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
_STAGE_NODE_MAP: dict[str, str] = {
    "prd_generation": "GeneratePRD",
    "design_generation": "GenerateDesign",
}
_STAGE_TARGETS_MS: dict[str, tuple[float, float]] = {
    "prd_generation": (45_000.0, 120_000.0),
    "design_generation": (90_000.0, 240_000.0),
    "end_to_end": (12.0 * 60.0 * 1000.0, 30.0 * 60.0 * 1000.0),
}

# Non-terminal run nodes (these block delete/restart)
_TERMINAL_RUN_NODES = {"EndSuccess", "EndFailed"}


async def _ensure_scaffold_owner(db: AsyncSession) -> uuid.UUID:
    result = await db.execute(select(User).where(User.id == _SCAFFOLD_OWNER_ID))
    user = result.scalar_one_or_none()
    if user:
        return user.id

    user = User(
        id=_SCAFFOLD_OWNER_ID,
        email="operator+scaffold@id8.local",
        role="operator",
    )
    db.add(user)
    await db.flush()
    return user.id


@router.post("/projects", operation_id="createProject", response_model=ProjectResponse, status_code=201)
async def create_project(body: CreateProjectRequest, db: AsyncSession = Depends(get_db)) -> Project:
    owner_user_id = await _ensure_scaffold_owner(db)
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title cannot be empty")
    initial_prompt = body.initial_prompt.strip()
    if not initial_prompt:
        raise HTTPException(status_code=422, detail="initial_prompt cannot be empty")

    # Default stack_json if not provided
    stack_data = (body.stack_json or DEFAULT_STACK).model_dump()

    project = Project(
        title=title,
        initial_prompt=initial_prompt,
        owner_user_id=owner_user_id,
        stack_json=stack_data,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/projects", operation_id="listProjects", response_model=ProjectListResponse)
async def list_projects(
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[ProjectListItem]]:
    query = select(Project).order_by(Project.updated_at.desc(), Project.created_at.desc())
    if not include_deleted:
        query = query.where(Project.deleted_at.is_(None))

    project_result = await db.execute(query)
    projects = list(project_result.scalars().all())
    if not projects:
        return {"items": []}

    project_ids = [project.id for project in projects]
    latest_runs_subq = (
        select(
            ProjectRun.id.label("id"),
            ProjectRun.project_id.label("project_id"),
            ProjectRun.status.label("status"),
            ProjectRun.current_node.label("current_node"),
            ProjectRun.updated_at.label("updated_at"),
            func.row_number()
            .over(
                partition_by=ProjectRun.project_id,
                order_by=(ProjectRun.created_at.desc(), ProjectRun.id.desc()),
            )
            .label("rn"),
        )
        .where(ProjectRun.project_id.in_(project_ids))
        .subquery()
    )

    run_result = await db.execute(select(latest_runs_subq).where(latest_runs_subq.c.rn == 1))
    latest_runs_by_project: dict[uuid.UUID, dict[str, object]] = {}
    for row in run_result:
        latest_runs_by_project[row.project_id] = {
            "id": row.id,
            "status": row.status,
            "current_node": row.current_node,
            "updated_at": row.updated_at,
        }

    items: list[ProjectListItem] = []
    for project in projects:
        payload = ProjectResponse.model_validate(project).model_dump()
        payload["latest_run"] = latest_runs_by_project.get(project.id)
        items.append(ProjectListItem.model_validate(payload))

    return {"items": items}


@router.get("/projects/{projectId}", operation_id="getProject", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID = Path(alias="projectId"),
    db: AsyncSession = Depends(get_db),
) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id, Project.deleted_at.is_(None)))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete(
    "/projects/{projectId}",
    operation_id="deleteProject",
    response_model=DeleteProjectResponse,
)
async def delete_project(
    project_id: uuid.UUID = Path(alias="projectId"),
    db: AsyncSession = Depends(get_db),
) -> DeleteProjectResponse:
    result = await db.execute(select(Project).where(Project.id == project_id, Project.deleted_at.is_(None)))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check for active (non-terminal) runs
    active_run_result = await db.execute(
        select(ProjectRun.id)
        .where(
            ProjectRun.project_id == project_id,
            ProjectRun.current_node.not_in(_TERMINAL_RUN_NODES),
        )
        .limit(1)
    )
    if active_run_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete project while a run is in progress",
        )

    now = datetime.now(tz=UTC)
    project.deleted_at = now
    project.updated_at = now

    await emit_audit_event(project_id, None, "project.deleted", {"deleted_at": now.isoformat()}, db)
    await db.commit()
    await db.refresh(project)

    return DeleteProjectResponse(id=project.id, deleted_at=project.deleted_at)


@router.patch(
    "/projects/{projectId}",
    operation_id="updateProject",
    response_model=ProjectResponse,
)
async def update_project(
    body: UpdateProjectRequest,
    project_id: uuid.UUID = Path(alias="projectId"),
    db: AsyncSession = Depends(get_db),
) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id, Project.deleted_at.is_(None)))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    changes: dict[str, object] = {}
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(status_code=422, detail="title cannot be empty")
        project.title = body.title.strip()
        changes["title"] = project.title

    if body.initial_prompt is not None:
        if not body.initial_prompt.strip():
            raise HTTPException(status_code=422, detail="initial_prompt cannot be empty")
        project.initial_prompt = body.initial_prompt.strip()
        changes["initial_prompt"] = project.initial_prompt

    if body.stack_json is not None:
        project.stack_json = body.stack_json.model_dump()
        changes["stack_json"] = project.stack_json

    if not changes:
        raise HTTPException(status_code=422, detail="No fields to update")

    project.updated_at = datetime.now(tz=UTC)
    await emit_audit_event(project_id, None, "project.updated", changes, db)
    await db.commit()
    await db.refresh(project)
    return project


@router.post(
    "/projects/{projectId}/restart",
    operation_id="restartProject",
    response_model=ProjectResponse,
    status_code=202,
)
async def restart_project(
    background_tasks: BackgroundTasks,
    project_id: uuid.UUID = Path(alias="projectId"),
    db: AsyncSession = Depends(get_db),
) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id, Project.deleted_at.is_(None)))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Block if active run exists
    active_run_result = await db.execute(
        select(ProjectRun.id)
        .where(
            ProjectRun.project_id == project_id,
            ProjectRun.current_node.not_in(_TERMINAL_RUN_NODES),
        )
        .limit(1)
    )
    if active_run_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot restart project while a run is in progress",
        )

    from app.orchestrator import NODE_TO_PROJECT_STATUS, NodeName

    start_node = NodeName.INGEST_PROMPT
    run = ProjectRun(
        project_id=project_id,
        status=NODE_TO_PROJECT_STATUS[start_node],
        current_node=start_node,
    )
    db.add(run)
    await db.flush()

    project.status = NODE_TO_PROJECT_STATUS[start_node]
    project.updated_at = datetime.now(tz=UTC)

    await emit_audit_event(
        project_id,
        None,
        "project.restarted",
        {"run_id": str(run.id), "start_node": str(start_node)},
        db,
    )
    await emit_audit_event(
        project_id,
        None,
        "orchestrator.run_started",
        {"run_id": str(run.id), "to_node": str(start_node), "outcome": "restarted"},
        db,
    )
    await db.commit()
    await db.refresh(project)
    await db.refresh(run)

    from app.routes.runs import _run_orchestrator_background

    background_tasks.add_task(_run_orchestrator_background, run.id)

    return project


@router.get(
    "/projects/{projectId}/metrics",
    operation_id="getProjectMetrics",
    response_model=ProjectMetricsResponse,
)
async def get_project_metrics(
    project_id: uuid.UUID = Path(alias="projectId"),
    db: AsyncSession = Depends(get_db),
) -> ProjectMetricsResponse:
    project_result = await db.execute(select(Project.id).where(Project.id == project_id))
    if project_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    events_result = await db.execute(
        select(AuditEvent).where(AuditEvent.project_id == project_id).order_by(AuditEvent.created_at.asc())
    )
    events = list(events_result.scalars().all())

    node_durations: dict[str, list[float]] = defaultdict(list)
    run_durations: list[float] = []

    profile_usage: dict[str, dict[str, float]] = defaultdict(
        lambda: {"prompt_tokens": 0.0, "completion_tokens": 0.0, "estimated_cost_usd": 0.0}
    )
    run_usage: dict[uuid.UUID, dict[str, float]] = defaultdict(
        lambda: {"prompt_tokens": 0.0, "completion_tokens": 0.0, "estimated_cost_usd": 0.0}
    )
    retry_by_node: dict[str, dict[str, float]] = defaultdict(lambda: {"retry_count": 0.0, "retry_delay_ms": 0.0})
    failure_reasons: Counter[str] = Counter()

    deploy_started = 0
    deploy_succeeded = 0
    deploy_failed = 0
    deploy_durations: list[float] = []

    for event in events:
        payload = event.event_payload if isinstance(event.event_payload, dict) else {}
        event_type = event.event_type

        if event_type == "run.node_completed":
            node = str(payload.get("node", "")).strip()
            duration_ms = _to_float(payload.get("duration_ms"))
            if node and duration_ms is not None:
                node_durations[node].append(duration_ms)

            failure_reason = str(payload.get("failure_reason", "")).strip()
            if failure_reason:
                failure_reasons[failure_reason] += 1

        elif event_type == "run.retry_scheduled":
            node = str(payload.get("node", "")).strip()
            if node:
                retry_by_node[node]["retry_count"] += 1.0
                retry_by_node[node]["retry_delay_ms"] += _to_float(payload.get("retry_delay_ms")) or 0.0
            failure_reason = str(payload.get("failure_reason", "")).strip()
            if failure_reason:
                failure_reasons[failure_reason] += 1

        elif event_type == "run.failed":
            failure_reason = str(payload.get("failure_reason", "")).strip()
            if failure_reason:
                failure_reasons[failure_reason] += 1
            duration_ms = _to_float(payload.get("total_duration_ms"))
            if duration_ms is not None:
                run_durations.append(duration_ms)

        elif event_type == "run.completed":
            duration_ms = _to_float(payload.get("total_duration_ms"))
            if duration_ms is not None:
                run_durations.append(duration_ms)

        elif event_type == "llm.usage_recorded":
            profile = str(payload.get("model_profile", "unknown")).strip() or "unknown"
            prompt_tokens = float(_to_int(payload.get("prompt_tokens")))
            completion_tokens = float(_to_int(payload.get("completion_tokens")))
            estimated_cost = _to_float(payload.get("estimated_cost_usd")) or 0.0

            profile_usage[profile]["prompt_tokens"] += prompt_tokens
            profile_usage[profile]["completion_tokens"] += completion_tokens
            profile_usage[profile]["estimated_cost_usd"] += estimated_cost

            run_id = _to_uuid(payload.get("run_id"))
            if run_id is not None:
                run_usage[run_id]["prompt_tokens"] += prompt_tokens
                run_usage[run_id]["completion_tokens"] += completion_tokens
                run_usage[run_id]["estimated_cost_usd"] += estimated_cost

        elif event_type == "deploy.started":
            deploy_started += 1
        elif event_type == "deploy.succeeded":
            deploy_succeeded += 1
            duration_ms = _to_float(payload.get("duration_ms"))
            if duration_ms is not None:
                deploy_durations.append(duration_ms)
        elif event_type == "deploy.failed":
            deploy_failed += 1

    node_latency_metrics = [
        NodeLatencyMetric(
            node=node,
            stats=DistributionMetric.model_validate(summarize_distribution(durations)),
        )
        for node, durations in sorted(node_durations.items(), key=lambda item: item[0])
    ]

    stage_slos: list[StageSloMetric] = []
    for stage, node in _STAGE_NODE_MAP.items():
        stats_dict = summarize_distribution(node_durations.get(node, []))
        p50 = _to_float(stats_dict.get("p50_ms"))
        p95 = _to_float(stats_dict.get("p95_ms"))
        target_p50_ms, target_p95_ms = _STAGE_TARGETS_MS[stage]
        stage_slos.append(
            StageSloMetric(
                stage=stage,
                stats=DistributionMetric.model_validate(stats_dict),
                target_p50_ms=target_p50_ms,
                target_p95_ms=target_p95_ms,
                meets_p50=(p50 <= target_p50_ms) if p50 is not None else None,
                meets_p95=(p95 <= target_p95_ms) if p95 is not None else None,
            )
        )

    end_to_end_stats = summarize_distribution(run_durations)
    end_to_end_p50 = _to_float(end_to_end_stats.get("p50_ms"))
    end_to_end_p95 = _to_float(end_to_end_stats.get("p95_ms"))
    end_to_end_targets = _STAGE_TARGETS_MS["end_to_end"]
    stage_slos.append(
        StageSloMetric(
            stage="end_to_end",
            stats=DistributionMetric.model_validate(end_to_end_stats),
            target_p50_ms=end_to_end_targets[0],
            target_p95_ms=end_to_end_targets[1],
            meets_p50=(end_to_end_p50 <= end_to_end_targets[0]) if end_to_end_p50 is not None else None,
            meets_p95=(end_to_end_p95 <= end_to_end_targets[1]) if end_to_end_p95 is not None else None,
        )
    )

    token_cost_by_profile: list[ProfileTokenCostMetric] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_estimated_cost = 0.0
    for profile, usage in sorted(profile_usage.items(), key=lambda item: item[0]):
        prompt_tokens = int(usage["prompt_tokens"])
        completion_tokens = int(usage["completion_tokens"])
        estimated_cost_usd = round(float(usage["estimated_cost_usd"]), 8)
        total_prompt_tokens += prompt_tokens
        total_completion_tokens += completion_tokens
        total_estimated_cost += estimated_cost_usd
        token_cost_by_profile.append(
            ProfileTokenCostMetric(
                model_profile=profile,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                estimated_cost_usd=estimated_cost_usd,
            )
        )

    token_cost_by_run = [
        RunTokenCostMetric(
            run_id=run_id,
            prompt_tokens=int(usage["prompt_tokens"]),
            completion_tokens=int(usage["completion_tokens"]),
            total_tokens=int(usage["prompt_tokens"] + usage["completion_tokens"]),
            estimated_cost_usd=round(float(usage["estimated_cost_usd"]), 8),
        )
        for run_id, usage in sorted(run_usage.items(), key=lambda item: str(item[0]))
    ]

    retry_metrics = [
        RetryMetric(
            node=node,
            retry_count=int(stats["retry_count"]),
            retry_delay_ms=round(float(stats["retry_delay_ms"]), 2),
        )
        for node, stats in sorted(retry_by_node.items(), key=lambda item: item[0])
    ]

    failure_metrics = [
        FailureReasonMetric(reason=reason, count=count)
        for reason, count in sorted(failure_reasons.items(), key=lambda item: item[0])
    ]

    deploy_attempts = max(deploy_started, deploy_succeeded + deploy_failed)
    success_rate = round(deploy_succeeded / deploy_attempts, 4) if deploy_attempts > 0 else None

    return ProjectMetricsResponse(
        project_id=project_id,
        generated_at=datetime.now(tz=UTC),
        node_latencies=node_latency_metrics,
        stage_slos=stage_slos,
        token_cost_totals=TokenCostTotals(
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_tokens=total_prompt_tokens + total_completion_tokens,
            estimated_cost_usd=round(total_estimated_cost, 8),
        ),
        token_cost_by_profile=token_cost_by_profile,
        token_cost_by_run=token_cost_by_run,
        retries=retry_metrics,
        failure_reasons=failure_metrics,
        deployment=DeploymentMetric(
            attempts=deploy_attempts,
            succeeded=deploy_succeeded,
            failed=deploy_failed,
            success_rate=success_rate,
            time_to_live_url=(
                DistributionMetric.model_validate(summarize_distribution(deploy_durations))
                if deploy_durations
                else None
            ),
        ),
    )


def _to_float(raw: Any) -> float | None:
    if isinstance(raw, (float, int)):
        return float(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _to_int(raw: Any) -> int:
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return 0
        try:
            return int(float(text))
        except ValueError:
            return 0
    return 0


def _to_uuid(raw: Any) -> uuid.UUID | None:
    if isinstance(raw, uuid.UUID):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            return uuid.UUID(text)
        except ValueError:
            return None
    return None
