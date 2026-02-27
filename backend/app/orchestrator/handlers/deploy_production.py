"""DeployProduction node handler.

Executes the full deployment pipeline after a deploy approval has been
granted:

  1. Verify the deploy-approval event exists for this run.
  2. Deploy to Vercel (create project if absent, inject env vars, trigger
     deployment, poll until READY).
  3. Health-check the live production URL.
  4. Create a ``DeploymentRecord`` in the database.
  5. Update ``projects.live_deployment_url``.
  6. Return a ``deploy_report`` artifact (persisted by the engine).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from app.config import settings
from app.deploy.vercel import VercelDeployTimeoutError, VercelError, deploy_to_vercel
from app.github.client import _parse_owner_repo
from app.models.approval_event import ApprovalEvent
from app.models.audit_event import AuditEvent
from app.models.deployment_record import DeploymentRecord
from app.models.enums import ApprovalStage, ArtifactType
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.observability import emit_audit_event
from app.orchestrator.base import NodeHandler, NodeResult, RunContext

logger = logging.getLogger("id8.orchestrator.handlers.deploy_production")

_HEALTH_CHECK_TIMEOUT = 30.0
_HEALTH_CHECK_ACCEPTED_PROTECTED_STATUSES = {401, 403}


class DeployProductionHandler(NodeHandler):
    """Run the Vercel-only deployment pipeline."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        await emit_audit_event(
            ctx.project_id,
            None,
            "deploy.started",
            {
                "run_id": str(ctx.run_id),
                "node": ctx.current_node,
                "environment": "production",
            },
            ctx.db,
        )
        # 1. Pre-check: deploy approval must exist.
        approval = await _load_deploy_approval(ctx)
        if approval is None:
            await _emit_deploy_failed_event(
                ctx,
                error="Deploy approval event not found; DeployProduction cannot proceed",
                stage="precheck",
            )
            return NodeResult(
                outcome="failure",
                error="Deploy approval event not found; DeployProduction cannot proceed",
            )

        # 2. Load code snapshot.
        snapshot = await _load_code_snapshot(ctx)
        if snapshot is None:
            await _emit_deploy_failed_event(
                ctx,
                error="No code_snapshot artifact found; DeployProduction cannot proceed",
                stage="precheck",
            )
            return NodeResult(
                outcome="failure",
                error="No code_snapshot artifact found; DeployProduction cannot proceed",
            )

        # 3. Load project for repo URL and existing deploy metadata.
        project = await _load_project(ctx)
        if project is None:
            await _emit_deploy_failed_event(
                ctx,
                error=f"Project {ctx.project_id} not found",
                stage="precheck",
            )
            return NodeResult(
                outcome="failure",
                error=f"Project {ctx.project_id} not found",
            )

        start_time = datetime.now(tz=UTC)

        # 4. Validate credentials.
        if not settings.vercel_token:
            return await _fail_deployment(
                ctx,
                project,
                error="VERCEL_TOKEN is not configured",
                provider_payload={"error": "VERCEL_TOKEN is not configured", "stage": "precheck"},
            )

        # 5. Resolve GitHub owner/repo.
        github_url = project.github_repo_url
        if not github_url:
            return await _fail_deployment(
                ctx,
                project,
                error="project.github_repo_url is not set; run PreparePR first",
                provider_payload={"error": "project.github_repo_url missing", "stage": "precheck"},
            )

        try:
            github_org, github_repo = _parse_owner_repo(github_url)
        except Exception as exc:
            return await _fail_deployment(
                ctx,
                project,
                error=f"Cannot parse GitHub repo URL: {exc}",
                provider_payload={"error": f"Cannot parse GitHub repo URL: {exc}", "stage": "precheck"},
            )

        # 6. Build publishable env vars for Vercel.
        env_vars: dict[str, str] = {}
        await _record_env_injection_audit(ctx, env_vars.keys())

        # 7. Vercel deployment.
        existing_project_id = _extract_existing_vercel_project_id(ctx)
        try:
            vercel_meta = await deploy_to_vercel(
                token=settings.vercel_token,
                team_id=settings.vercel_team_id or None,
                project_name=_project_name(ctx),
                github_org=github_org,
                github_repo=github_repo,
                env_vars=env_vars,
                existing_project_id=existing_project_id,
            )
        except VercelDeployTimeoutError as exc:
            return await _fail_deployment(
                ctx,
                project,
                error=str(exc),
                provider_payload={"error": str(exc), "stage": "vercel_poll_timeout"},
                rollback_candidate=True,
            )
        except VercelError as exc:
            return await _fail_deployment(
                ctx,
                project,
                error=f"Vercel deployment failed: {exc}",
                provider_payload={"error": str(exc), "stage": "vercel"},
                rollback_candidate=True,
            )

        if vercel_meta.get("state") != "READY":
            return await _fail_deployment(
                ctx,
                project,
                error=f"Vercel deployment ended in state '{vercel_meta.get('state')}' — not READY",
                provider_payload=vercel_meta,
                rollback_candidate=True,
            )

        production_url: str = vercel_meta.get("production_url") or vercel_meta.get("deployment_url", "")

        # 8. Health check.
        health_ok, health_detail = await _health_check(production_url)
        if not health_ok:
            return await _fail_deployment(
                ctx,
                project,
                error=f"Production health check failed for {production_url}: {health_detail}",
                provider_payload={
                    **vercel_meta,
                    "health_check": {"ok": health_ok, "detail": health_detail},
                },
                rollback_candidate=True,
            )

        # 9. Persist DeploymentRecord.
        end_time = datetime.now(tz=UTC)
        provider_payload: dict[str, Any] = {
            **vercel_meta,
            "health_check": {"ok": health_ok, "detail": health_detail},
            "started_at": start_time.isoformat(),
            "finished_at": end_time.isoformat(),
        }
        await _create_or_update_deployment_record(
            ctx,
            status="success",
            deployment_url=production_url,
            provider_payload=provider_payload,
        )

        # 10. Update project.live_deployment_url.
        project.live_deployment_url = production_url
        project.updated_at = end_time
        await ctx.db.flush()

        logger.info(
            "DeployProduction succeeded for run=%s url=%s",
            ctx.run_id,
            production_url,
        )
        await emit_audit_event(
            ctx.project_id,
            None,
            "deploy.succeeded",
            {
                "run_id": str(ctx.run_id),
                "environment": "production",
                "deployment_url": production_url,
                "duration_ms": round((end_time - start_time).total_seconds() * 1000, 2),
            },
            ctx.db,
        )

        artifact_data: dict[str, Any] = {
            "live_url": production_url,
            "environment": "production",
            "vercel": vercel_meta,
            "health_check": {"ok": health_ok, "detail": health_detail},
            "github_repo": github_url,
            "started_at": start_time.isoformat(),
            "finished_at": end_time.isoformat(),
        }

        return NodeResult(
            outcome="passed",
            artifact_data=artifact_data,
            context_updates={
                "live_url": production_url,
                "vercel_project_id": vercel_meta.get("vercel_project_id"),
            },
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_deploy_approval(ctx: RunContext) -> ApprovalEvent | None:
    result = await ctx.db.execute(
        select(ApprovalEvent)
        .where(
            ApprovalEvent.run_id == ctx.run_id,
            ApprovalEvent.stage == ApprovalStage.DEPLOY,
            ApprovalEvent.decision == "approved",
        )
        .order_by(ApprovalEvent.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _load_code_snapshot(ctx: RunContext) -> dict[str, Any] | None:
    result = await ctx.db.execute(
        select(ProjectArtifact)
        .where(
            ProjectArtifact.run_id == ctx.run_id,
            ProjectArtifact.artifact_type == ArtifactType.CODE_SNAPSHOT,
        )
        .order_by(ProjectArtifact.version.desc())
        .limit(1)
    )
    artifact = result.scalar_one_or_none()
    return artifact.content if artifact is not None else None


async def _load_project(ctx: RunContext) -> Project | None:
    result = await ctx.db.execute(select(Project).where(Project.id == ctx.project_id))
    return result.scalar_one_or_none()


def _extract_sql_files(files: list[dict[str, str]]) -> list[dict[str, str]]:
    """Legacy helper retained for compatibility with existing tests/tooling."""
    return [
        f
        for f in files
        if (
            f.get("language", "").lower() == "sql"
            or str(f.get("path", "")).endswith(".sql")
            or "migration" in str(f.get("path", "")).lower()
        )
    ]


def _project_name(ctx: RunContext) -> str:
    short = str(ctx.project_id).replace("-", "")[:12]
    return f"id8-{short}"


def _extract_existing_vercel_project_id(ctx: RunContext) -> str | None:
    """Return a previously stored vercel_project_id from workflow context."""
    return ctx.workflow_payload.get("vercel_project_id")


async def _health_check(url: str, *, timeout: float = _HEALTH_CHECK_TIMEOUT) -> tuple[bool, str]:
    """GET *url* and return (ok, detail).  Never raises."""
    if not url:
        return False, "No URL to health-check"
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.get(url, follow_redirects=True)
        if 200 <= resp.status_code < 400:
            return True, f"HTTP {resp.status_code}"
        if resp.status_code in _HEALTH_CHECK_ACCEPTED_PROTECTED_STATUSES:
            return True, f"HTTP {resp.status_code} (reachable, auth-protected)"
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


async def _record_env_injection_audit(ctx: RunContext, keys: Any) -> None:
    """Record publishable env-var names injected into deployment runtime."""
    key_names = sorted({str(k) for k in keys if str(k)})
    if not key_names:
        return

    event = AuditEvent(
        project_id=ctx.project_id,
        actor_user_id=None,
        event_type="deploy.env_vars_injected",
        event_payload={
            "run_id": str(ctx.run_id),
            "keys": key_names,
        },
    )
    ctx.db.add(event)
    await ctx.db.flush()


async def _create_or_update_deployment_record(
    ctx: RunContext,
    *,
    status: str,
    deployment_url: str | None,
    provider_payload: dict[str, Any],
) -> DeploymentRecord:
    """Update an existing queued DeploymentRecord or create a new one."""
    now = datetime.now(tz=UTC)

    # Look for an existing queued record from this route trigger.
    result = await ctx.db.execute(
        select(DeploymentRecord)
        .where(
            DeploymentRecord.run_id == ctx.run_id,
            DeploymentRecord.environment == "production",
            DeploymentRecord.status == "queued",
        )
        .order_by(DeploymentRecord.created_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()

    if record is not None:
        record.status = status
        record.deployment_url = deployment_url
        record.provider_payload = provider_payload
        record.updated_at = now
    else:
        record = DeploymentRecord(
            project_id=ctx.project_id,
            run_id=ctx.run_id,
            environment="production",
            status=status,
            deployment_url=deployment_url,
            provider_payload=provider_payload,
        )
        ctx.db.add(record)

    await ctx.db.flush()
    return record


async def _fail_deployment(
    ctx: RunContext,
    project: Project,
    *,
    error: str,
    provider_payload: dict[str, Any],
    rollback_candidate: bool = False,
) -> NodeResult:
    """Record a failed deployment and return a failure NodeResult."""
    if rollback_candidate:
        provider_payload["rollback_candidate"] = True

    await _create_or_update_deployment_record(
        ctx,
        status="failed",
        deployment_url=None,
        provider_payload=provider_payload,
    )

    logger.error("DeployProduction failed for run=%s: %s", ctx.run_id, error)
    await _emit_deploy_failed_event(
        ctx,
        error=error,
        stage=str(provider_payload.get("stage", "deploy")),
    )

    return NodeResult(
        outcome="failure",
        error=error,
        artifact_data={
            "live_url": None,
            "environment": "production",
            "error": error,
            "rollback_candidate": rollback_candidate,
            "provider_payload": provider_payload,
        },
    )


async def _emit_deploy_failed_event(
    ctx: RunContext,
    *,
    error: str,
    stage: str,
) -> None:
    await emit_audit_event(
        ctx.project_id,
        None,
        "deploy.failed",
        {
            "run_id": str(ctx.run_id),
            "environment": "production",
            "stage": stage,
            "error": error,
        },
        ctx.db,
    )
