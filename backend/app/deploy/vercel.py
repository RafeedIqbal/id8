"""Vercel deployment client for ID8.

Manages Vercel project creation, environment variable injection (filtered
through ``secret_filter``), deployment triggering, and status polling.

Only publishable environment variables are ever set on Vercel projects.
The ``secret_filter`` is applied before any API call that touches env vars.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.deploy.secret_filter import assert_no_secrets, filter_env_vars

logger = logging.getLogger("id8.deploy.vercel")

_BASE_URL = "https://api.vercel.com"
_MAX_RETRIES = 5
_DEPLOY_POLL_INTERVAL = 10.0
_DEPLOY_TIMEOUT = 600.0  # 10 minutes

_TERMINAL_STATES = frozenset({"READY", "ERROR", "CANCELED"})


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VercelProject:
    id: str
    name: str
    framework: str | None
    production_url: str | None


@dataclass(frozen=True, slots=True)
class VercelDeployment:
    id: str
    url: str  # preview URL, e.g. my-app-abc123.vercel.app
    state: str  # BUILDING | READY | ERROR | INITIALIZING | QUEUED | CANCELED
    ready_state: str
    production_url: str | None  # alias if available


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VercelError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class VercelAuthError(VercelError):
    """Authentication failure (401 / 403)."""


class VercelDeployTimeoutError(VercelError):
    """Deployment did not reach READY within the allowed window."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class VercelClient:
    """Async Vercel API client."""

    def __init__(self, token: str, *, team_id: str | None = None) -> None:
        self._token = token
        self._team_id = team_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _params(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        p: dict[str, str] = {}
        if self._team_id:
            p["teamId"] = self._team_id
        if extra:
            p.update(extra)
        return p

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        url = f"{_BASE_URL}{path}"
        all_params = self._params(params)

        for attempt in range(_MAX_RETRIES):
            async with httpx.AsyncClient(timeout=30) as http:
                resp = await http.request(
                    method, url, headers=self._headers(), json=body, params=all_params
                )

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2.0 ** attempt))
                logger.warning("Vercel rate limit; retrying after %.0f s", retry_after)
                await asyncio.sleep(retry_after)
                continue

            if resp.status_code in (401, 403):
                raise VercelAuthError(
                    f"Vercel auth failed ({resp.status_code}): {resp.text}",
                    status_code=resp.status_code,
                )

            if resp.status_code >= 400:
                raise VercelError(
                    f"Vercel API error {resp.status_code}: {resp.text}",
                    status_code=resp.status_code,
                )

            if resp.status_code == 204:
                return None

            return resp.json()

        raise VercelError("Vercel request exhausted retries")

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    async def get_project(self, name_or_id: str) -> VercelProject:
        data: dict[str, Any] = await self._request("GET", f"/v9/projects/{name_or_id}")
        return _project_from_json(data)

    async def create_project(
        self,
        name: str,
        *,
        framework: str = "nextjs",
        github_repo: str | None = None,
        github_org: str | None = None,
    ) -> VercelProject:
        """Create a Vercel project, optionally linked to a GitHub repo."""
        body: dict[str, Any] = {"name": name, "framework": framework}
        if github_repo and github_org:
            body["gitRepository"] = {
                "type": "github",
                "repo": f"{github_org}/{github_repo}",
            }
        data: dict[str, Any] = await self._request("POST", "/v9/projects", body=body)
        return _project_from_json(data)

    # ------------------------------------------------------------------
    # Environment variables
    # ------------------------------------------------------------------

    async def set_env_vars(
        self,
        project_id: str,
        vars: dict[str, str],
        *,
        target: list[str] | None = None,
    ) -> None:
        """Set environment variables on a Vercel project.

        *vars* is filtered through ``secret_filter`` before any API call.
        Raises ``ValueError`` if any non-publishable keys slip through.
        """
        safe_vars = filter_env_vars(vars)
        assert_no_secrets(safe_vars)

        if not safe_vars:
            logger.info("set_env_vars: no publishable vars to inject for project %s", project_id)
            return

        deploy_targets = target or ["production", "preview", "development"]

        env_entries = [
            {
                "key": k,
                "value": v,
                "type": "plain",
                "target": deploy_targets,
            }
            for k, v in safe_vars.items()
        ]

        await self._request(
            "POST",
            f"/v10/projects/{project_id}/env",
            body=env_entries,
            # Keep repeated deploys idempotent: update existing keys if present.
            params={"upsert": "true"},
        )
        logger.info(
            "Injected %d env var(s) into Vercel project %s: %s",
            len(safe_vars),
            project_id,
            ", ".join(sorted(safe_vars)),
        )

    # ------------------------------------------------------------------
    # Deployments
    # ------------------------------------------------------------------

    async def create_deployment(
        self,
        project_id: str,
        *,
        github_org: str | None = None,
        github_repo: str | None = None,
        ref: str = "main",
        name: str | None = None,
    ) -> VercelDeployment:
        """Trigger a new deployment for *project_id* from the GitHub *ref*."""
        body: dict[str, Any] = {
            "name": name or project_id,
            "project": project_id,
            "target": "production",
        }
        if github_org and github_repo:
            body["gitSource"] = {
                "type": "github",
                "org": github_org,
                "repo": github_repo,
                "ref": ref,
            }
        data: dict[str, Any] = await self._request("POST", "/v13/deployments", body=body)
        return _deployment_from_json(data)

    async def get_deployment(self, deployment_id: str) -> VercelDeployment:
        data: dict[str, Any] = await self._request("GET", f"/v13/deployments/{deployment_id}")
        return _deployment_from_json(data)

    async def poll_deployment(
        self,
        deployment_id: str,
        *,
        timeout: float = _DEPLOY_TIMEOUT,
        interval: float = _DEPLOY_POLL_INTERVAL,
    ) -> VercelDeployment:
        """Poll *deployment_id* until it reaches a terminal state or times out.

        Returns the final ``VercelDeployment``.
        Raises ``VercelDeployTimeoutError`` on timeout.
        """
        deadline = time.monotonic() + timeout
        while True:
            deployment = await self.get_deployment(deployment_id)

            if deployment.state in _TERMINAL_STATES:
                logger.info(
                    "Vercel deployment %s reached state=%s url=%s",
                    deployment_id,
                    deployment.state,
                    deployment.url,
                )
                return deployment

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VercelDeployTimeoutError(
                    f"Vercel deployment {deployment_id} did not reach READY within "
                    f"{timeout:.0f}s (last state: {deployment.state})"
                )

            wait = min(interval, remaining)
            logger.info(
                "Vercel deployment %s state=%s; waiting %.0f s …",
                deployment_id,
                deployment.state,
                wait,
            )
            await asyncio.sleep(wait)


# ---------------------------------------------------------------------------
# JSON deserialisers
# ---------------------------------------------------------------------------


def _project_from_json(data: dict[str, Any]) -> VercelProject:
    aliases = data.get("alias", []) or []
    production_url: str | None = None
    for alias in aliases:
        if isinstance(alias, dict) and alias.get("domain"):
            production_url = f"https://{alias['domain']}"
            break
    link = data.get("link", {}) or {}
    return VercelProject(
        id=data["id"],
        name=data["name"],
        framework=data.get("framework"),
        production_url=production_url or link.get("productionDeploymentsFastLane"),
    )


def _deployment_from_json(data: dict[str, Any]) -> VercelDeployment:
    raw_url: str = data.get("url", "")
    url = f"https://{raw_url}" if raw_url and not raw_url.startswith("http") else raw_url
    state: str = data.get("state", data.get("readyState", "QUEUED"))
    ready_state: str = data.get("readyState", state)

    # Prefer the aliasAssigned URL (production domain) when available.
    production_url: str | None = None
    alias = data.get("alias", []) or []
    for item in alias:
        if isinstance(item, dict) and item.get("domain"):
            production_url = f"https://{item['domain']}"
            break

    return VercelDeployment(
        id=data["id"],
        url=url,
        state=state,
        ready_state=ready_state,
        production_url=production_url or url,
    )


# ---------------------------------------------------------------------------
# High-level deploy helper
# ---------------------------------------------------------------------------


async def deploy_to_vercel(
    *,
    token: str,
    team_id: str | None,
    project_name: str,
    github_org: str,
    github_repo: str,
    env_vars: dict[str, str],
    existing_project_id: str | None = None,
) -> dict[str, Any]:
    """Provision a Vercel project and deploy from the merged main branch.

    *env_vars* is filtered through ``secret_filter`` automatically.

    Returns metadata safe for artifact storage:
    ``{"vercel_project_id", "deployment_id", "deployment_url",
       "production_url", "state"}``.
    """
    client = VercelClient(token, team_id=team_id if team_id else None)

    if existing_project_id:
        try:
            vproject = await client.get_project(existing_project_id)
            logger.info("Using existing Vercel project %s", existing_project_id)
        except VercelError:
            existing_project_id = None

    if not existing_project_id:
        try:
            vproject = await client.get_project(project_name)
            logger.info("Using existing Vercel project by name %s (id=%s)", project_name, vproject.id)
        except VercelError as exc:
            if exc.status_code != 404:
                raise
            vproject = await client.create_project(
                project_name,
                framework="nextjs",
                github_repo=github_repo,
                github_org=github_org,
            )
            logger.info("Created Vercel project %s (id=%s)", project_name, vproject.id)

    # Inject publishable env vars.
    await client.set_env_vars(vproject.id, env_vars)

    # Trigger deployment from merged main.
    deployment = await client.create_deployment(
        vproject.id,
        github_org=github_org,
        github_repo=github_repo,
        ref="main",
        name=project_name,
    )
    logger.info("Triggered Vercel deployment %s", deployment.id)

    # Poll until READY or error.
    final = await client.poll_deployment(deployment.id)

    return {
        "vercel_project_id": vproject.id,
        "deployment_id": final.id,
        "deployment_url": final.url,
        "production_url": final.production_url or final.url,
        "state": final.state,
    }
