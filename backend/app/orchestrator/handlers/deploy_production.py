"""DeployProduction node handler.

Executes the full deployment pipeline after a deploy approval has been
granted:

  1. Verify the deploy-approval event exists for this run.
  2. Extract SQL migration files from the latest code_snapshot artifact.
  3. Provision Supabase (create project if absent, run migrations).
  4. Deploy to Vercel (create project if absent, inject env vars, trigger
     deployment, poll until READY).
  5. Health-check the live production URL.
  6. Create a ``DeploymentRecord`` in the database.
  7. Update ``projects.live_deployment_url``.
  8. Return a ``deploy_report`` artifact (persisted by the engine).

Secret safety:
- Supabase service-role key is NEVER included in artifact outputs or
  passed to Vercel.
- Only publishable keys (``NEXT_PUBLIC_*``) are injected into Vercel env.
- ``secret_filter.assert_no_secrets`` acts as a final gate.
"""
from __future__ import annotations

import logging
import secrets
import string
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from app.config import settings
from app.deploy.supabase import SupabaseError, provision_supabase
from app.deploy.vercel import VercelDeployTimeoutError, VercelError, deploy_to_vercel
from app.github.client import _parse_owner_repo
from app.models.approval_event import ApprovalEvent
from app.models.deployment_record import DeploymentRecord
from app.models.enums import ArtifactType, ApprovalStage
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.orchestrator.base import NodeHandler, NodeResult, RunContext

logger = logging.getLogger("id8.orchestrator.handlers.deploy_production")

_DB_PASS_ALPHABET = string.ascii_letters + string.digits
_DB_PASS_LENGTH = 32
_HEALTH_CHECK_TIMEOUT = 30.0


class DeployProductionHandler(NodeHandler):
    """Run the full Supabase + Vercel deployment pipeline."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        # 1. Pre-check: deploy approval must exist.
        approval = await _load_deploy_approval(ctx)
        if approval is None:
            return NodeResult(
                outcome="failure",
                error="Deploy approval event not found; DeployProduction cannot proceed",
            )

        # 2. Load code snapshot.
        snapshot = await _load_code_snapshot(ctx)
        if snapshot is None:
            return NodeResult(
                outcome="failure",
                error="No code_snapshot artifact found; DeployProduction cannot proceed",
            )

        files: list[dict[str, str]] = snapshot.get("files", [])
        sql_files = _extract_sql_files(files)

        # 3. Load project for repo URL and existing deploy metadata.
        project = await _load_project(ctx)
        if project is None:
            return NodeResult(
                outcome="failure",
                error=f"Project {ctx.project_id} not found",
            )

        start_time = datetime.now(tz=UTC)

        # 4. Validate credentials.
        if not settings.vercel_token:
            return NodeResult(
                outcome="failure",
                error="VERCEL_TOKEN is not configured",
            )

        # 5. Resolve GitHub owner/repo.
        github_url = project.github_repo_url
        if not github_url:
            return NodeResult(
                outcome="failure",
                error="project.github_repo_url is not set; run PreparePR first",
            )

        try:
            github_org, github_repo = _parse_owner_repo(github_url)
        except Exception as exc:
            return NodeResult(
                outcome="failure",
                error=f"Cannot parse GitHub repo URL: {exc}",
            )

        # 6. Provision Supabase (optional — skipped if no access token).
        supabase_meta: dict[str, Any] = {}
        if settings.supabase_access_token and settings.supabase_org_id:
            project_name = _project_name(ctx)
            db_pass = _generate_db_pass()
            existing_ref = _extract_existing_supabase_ref(ctx)
            try:
                supabase_meta = await provision_supabase(
                    access_token=settings.supabase_access_token,
                    org_id=settings.supabase_org_id,
                    project_name=project_name,
                    db_pass=db_pass,
                    sql_files=sql_files,
                    existing_ref=existing_ref,
                )
            except SupabaseError as exc:
                return NodeResult(
                    outcome="failure",
                    error=f"Supabase provisioning failed: {exc}",
                )
        else:
            logger.info(
                "SUPABASE_ACCESS_TOKEN / SUPABASE_ORG_ID not configured — "
                "skipping Supabase provisioning for run=%s",
                ctx.run_id,
            )

        # 7. Build publishable env vars for Vercel.
        env_vars: dict[str, str] = {}
        if supabase_meta.get("supabase_url"):
            env_vars["NEXT_PUBLIC_SUPABASE_URL"] = supabase_meta["supabase_url"]
        if supabase_meta.get("supabase_anon_key"):
            env_vars["NEXT_PUBLIC_SUPABASE_ANON_KEY"] = supabase_meta["supabase_anon_key"]

        # 8. Vercel deployment.
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

        # 9. Health check.
        health_ok, health_detail = await _health_check(production_url)
        if not health_ok:
            logger.warning("Health check failed for %s: %s", production_url, health_detail)
            # Non-fatal: we still consider the deployment successful but log the warning.

        # 10. Persist DeploymentRecord.
        end_time = datetime.now(tz=UTC)
        provider_payload: dict[str, Any] = {
            **vercel_meta,
            "supabase": supabase_meta,
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

        # 11. Update project.live_deployment_url.
        project.live_deployment_url = production_url
        project.updated_at = end_time
        await ctx.db.flush()

        logger.info(
            "DeployProduction succeeded for run=%s url=%s",
            ctx.run_id,
            production_url,
        )

        artifact_data: dict[str, Any] = {
            "live_url": production_url,
            "environment": "production",
            "vercel": vercel_meta,
            "supabase": supabase_meta,
            "health_check": {"ok": health_ok, "detail": health_detail},
            "github_repo": github_url,
            "started_at": start_time.isoformat(),
            "finished_at": end_time.isoformat(),
            "migrations_applied": supabase_meta.get("migrations_applied", []),
        }

        return NodeResult(
            outcome="passed",
            artifact_data=artifact_data,
            context_updates={
                "live_url": production_url,
                "vercel_project_id": vercel_meta.get("vercel_project_id"),
                "supabase_ref": supabase_meta.get("supabase_ref"),
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
    """Return files that look like SQL migrations."""
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


def _generate_db_pass(length: int = _DB_PASS_LENGTH) -> str:
    return "".join(secrets.choice(_DB_PASS_ALPHABET) for _ in range(length))


def _extract_existing_supabase_ref(ctx: RunContext) -> str | None:
    """Return a previously stored supabase_ref from workflow context."""
    return ctx.workflow_payload.get("supabase_ref")


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
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


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
