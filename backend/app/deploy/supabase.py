"""Supabase Management API client for ID8.

Provisions a dedicated Supabase project for each generated application,
runs database migrations, and returns publishable connection metadata.

Authentication uses a Supabase Personal Access Token (PAT) passed via
``SUPABASE_ACCESS_TOKEN``.  The service-role key is retrieved from the API
but is NEVER surfaced in artifact outputs — only the anon (publishable) key
is returned.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("id8.deploy.supabase")

_BASE_URL = "https://api.supabase.com"
_MAX_RETRIES = 5
_PROVISION_POLL_INTERVAL = 10.0
_PROVISION_TIMEOUT = 300.0  # 5 minutes for project to come up


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SupabaseProject:
    """Minimal representation of a Supabase project."""

    ref: str  # 20-char project identifier
    name: str
    region: str
    status: str  # ACTIVE_HEALTHY | COMING_UP | INACTIVE | …
    db_host: str
    # Publishable key — safe to expose in frontend config
    anon_key: str
    # Connection string uses the project URL, not db_host directly
    api_url: str


class SupabaseError(Exception):
    """Base error for Supabase Management API failures."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SupabaseAuthError(SupabaseError):
    """Authentication failure (401 / 403)."""


class SupabaseProvisionTimeoutError(SupabaseError):
    """Project did not reach ACTIVE_HEALTHY within the allowed window."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class SupabaseClient:
    """Async Supabase Management API client."""

    def __init__(self, access_token: str) -> None:
        self._token = access_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{_BASE_URL}{path}"
        for attempt in range(_MAX_RETRIES):
            async with httpx.AsyncClient(timeout=30) as http:
                resp = await http.request(method, url, headers=self._headers(), json=body)

            if resp.status_code == 429:
                backoff = 2.0 ** attempt
                logger.warning("Supabase rate limit; retrying after %.0f s", backoff)
                await asyncio.sleep(backoff)
                continue

            if resp.status_code in (401, 403):
                raise SupabaseAuthError(
                    f"Supabase auth failed ({resp.status_code}): {resp.text}",
                    status_code=resp.status_code,
                )

            if resp.status_code >= 400:
                raise SupabaseError(
                    f"Supabase API error {resp.status_code}: {resp.text}",
                    status_code=resp.status_code,
                )

            if resp.status_code == 204:
                return None

            return resp.json()

        raise SupabaseError("Supabase request exhausted retries")

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------

    async def list_projects(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = await self._request("GET", "/v1/projects")
        return result

    async def get_project(self, ref: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._request("GET", f"/v1/projects/{ref}")
        return result

    async def create_project(
        self,
        *,
        name: str,
        org_id: str,
        db_pass: str,
        region: str = "us-east-1",
    ) -> dict[str, Any]:
        """Create a new Supabase project and return its raw representation."""
        body: dict[str, Any] = {
            "name": name,
            "organization_id": org_id,
            "db_pass": db_pass,
            "region": region,
        }
        result: dict[str, Any] = await self._request("POST", "/v1/projects", body=body)
        return result

    async def wait_for_active(
        self,
        ref: str,
        *,
        timeout: float = _PROVISION_TIMEOUT,
        interval: float = _PROVISION_POLL_INTERVAL,
    ) -> dict[str, Any]:
        """Poll until the project status is ACTIVE_HEALTHY.

        Returns the final project dict.  Raises
        ``SupabaseProvisionTimeoutError`` if the deadline is exceeded.
        """
        import time

        deadline = time.monotonic() + timeout
        while True:
            project = await self.get_project(ref)
            status: str = project.get("status", "")

            if status == "ACTIVE_HEALTHY":
                logger.info("Supabase project %s is ACTIVE_HEALTHY", ref)
                return project

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SupabaseProvisionTimeoutError(
                    f"Supabase project {ref} did not become ACTIVE_HEALTHY within {timeout:.0f}s "
                    f"(last status: {status})"
                )

            wait = min(interval, remaining)
            logger.info(
                "Supabase project %s status=%s; waiting %.0f s …",
                ref,
                status,
                wait,
            )
            await asyncio.sleep(wait)

    async def get_api_keys(self, ref: str) -> dict[str, str]:
        """Return a dict of {name: key} for the project.

        Only the ``anon`` key should be used in publishable configs.
        The ``service_role`` key must stay backend-only.
        """
        keys: list[dict[str, Any]] = await self._request("GET", f"/v1/projects/{ref}/api-keys")
        return {str(item["name"]): str(item["api_key"]) for item in keys}

    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------

    async def run_sql(self, ref: str, sql: str) -> Any:
        """Execute *sql* against the project database via the Management API."""
        body: dict[str, Any] = {"query": sql}
        result = await self._request("POST", f"/v1/projects/{ref}/database/query", body=body)
        logger.info("Ran SQL migration on Supabase project %s (%d chars)", ref, len(sql))
        return result

    async def run_migrations(self, ref: str, sql_files: list[dict[str, str]]) -> list[str]:
        """Run each SQL migration file in order.

        *sql_files* is a list of ``{"path": str, "content": str}`` dicts.
        Files are executed in sorted order by path.

        Returns the list of executed file paths.
        """
        sorted_files = sorted(sql_files, key=lambda f: f.get("path", ""))
        executed: list[str] = []
        for file in sorted_files:
            path = file.get("path", "")
            content = file.get("content", "").strip()
            if not content:
                continue
            try:
                await self.run_sql(ref, content)
                executed.append(path)
                logger.info("Applied migration: %s", path)
            except SupabaseError as exc:
                logger.error("Migration failed for %s: %s", path, exc)
                raise SupabaseError(f"Migration failed for {path}: {exc}") from exc
        return executed


# ---------------------------------------------------------------------------
# High-level provisioning helper
# ---------------------------------------------------------------------------


async def provision_supabase(
    *,
    access_token: str,
    org_id: str,
    project_name: str,
    db_pass: str,
    sql_files: list[dict[str, str]],
    region: str = "us-east-1",
    existing_ref: str | None = None,
) -> dict[str, Any]:
    """Provision a Supabase project and run migrations.

    If *existing_ref* is provided, the project is assumed to already exist
    and we skip creation.  Migrations are always applied (idempotent SQL is
    expected).

    Returns a metadata dict safe to store in artifact content:
    ``{"supabase_ref", "supabase_url", "supabase_anon_key",
       "migrations_applied", "region"}``.

    The service-role key is intentionally NOT included in the return value.
    """
    client = SupabaseClient(access_token)

    if existing_ref:
        ref = existing_ref
        project = await client.wait_for_active(ref)
        logger.info("Using existing Supabase project ref=%s", ref)
    else:
        raw = await client.create_project(
            name=project_name,
            org_id=org_id,
            db_pass=db_pass,
            region=region,
        )
        ref = str(raw["id"])
        logger.info("Created Supabase project ref=%s name=%s", ref, project_name)
        project = await client.wait_for_active(ref)

    keys = await client.get_api_keys(ref)
    anon_key = keys.get("anon", "")
    # Explicitly do NOT expose service_role in the return value.

    migrations_applied = await client.run_migrations(ref, sql_files)

    api_url = f"https://{ref}.supabase.co"

    return {
        "supabase_ref": ref,
        "supabase_url": api_url,
        "supabase_anon_key": anon_key,
        "migrations_applied": migrations_applied,
        "region": project.get("region", region),
    }
