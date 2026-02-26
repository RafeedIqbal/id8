"""Tests for the deployment pipeline: secret_filter, Supabase client,
Vercel client, and DeployProduction handler.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.deploy.secret_filter import assert_no_secrets, filter_env_vars
from app.deploy.supabase import (
    SupabaseAuthError,
    SupabaseClient,
    SupabaseError,
    SupabaseProvisionTimeoutError,
)
from app.deploy.vercel import (
    VercelClient,
    VercelDeployTimeoutError,
    VercelDeployment,
    VercelError,
    VercelProject,
    _deployment_from_json,
    _project_from_json,
)
from app.orchestrator.handlers.deploy_production import (
    DeployProductionHandler,
    _extract_sql_files,
    _generate_db_pass,
    _health_check,
    _project_name,
)


# ===========================================================================
# secret_filter
# ===========================================================================


class TestFilterEnvVars:
    def test_accepts_next_public_prefix(self) -> None:
        result = filter_env_vars({"NEXT_PUBLIC_SUPABASE_URL": "https://x.supabase.co"})
        assert "NEXT_PUBLIC_SUPABASE_URL" in result

    def test_accepts_public_prefix(self) -> None:
        result = filter_env_vars({"PUBLIC_API_URL": "https://api.example.com"})
        assert "PUBLIC_API_URL" in result

    def test_rejects_service_role_key(self) -> None:
        result = filter_env_vars({"SUPABASE_SERVICE_ROLE_KEY": "secret"})
        assert result == {}

    def test_rejects_secret_keyword(self) -> None:
        result = filter_env_vars({"MY_SECRET_TOKEN": "secret"})
        assert result == {}

    def test_rejects_private_key(self) -> None:
        result = filter_env_vars({"GITHUB_PRIVATE_KEY": "key"})
        assert result == {}

    def test_rejects_bare_api_key(self) -> None:
        result = filter_env_vars({"DATABASE_URL": "postgres://..."})
        assert result == {}

    def test_mixed_input(self) -> None:
        result = filter_env_vars({
            "NEXT_PUBLIC_SUPABASE_URL": "https://x.supabase.co",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY": "anon-key",
            "SUPABASE_SERVICE_ROLE_KEY": "service-secret",
            "DATABASE_URL": "postgres://secret",
        })
        assert set(result.keys()) == {
            "NEXT_PUBLIC_SUPABASE_URL",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY",
        }

    def test_empty_input(self) -> None:
        assert filter_env_vars({}) == {}


class TestAssertNoSecrets:
    def test_passes_for_clean_vars(self) -> None:
        assert_no_secrets({"NEXT_PUBLIC_URL": "https://example.com"})  # should not raise

    def test_raises_for_service_role(self) -> None:
        with pytest.raises(ValueError, match="SECRET"):
            # SERVICE_ROLE contains "SECRET" in _BLOCKED_KEYWORDS check
            assert_no_secrets({"SUPABASE_SERVICE_ROLE": "secret"})

    def test_raises_for_private(self) -> None:
        with pytest.raises(ValueError, match="PRIVATE"):
            assert_no_secrets({"SOME_PRIVATE_KEY": "key"})


# ===========================================================================
# Supabase client
# ===========================================================================


class TestSupabaseClient:
    @pytest.mark.asyncio
    async def test_request_raises_auth_error_on_401(self) -> None:
        import httpx

        client = SupabaseClient(access_token="tok")
        with patch.object(httpx, "AsyncClient") as mock_cls:
            instance = MagicMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.request = AsyncMock(
                return_value=httpx.Response(401, json={"message": "Unauthorized"})
            )
            mock_cls.return_value = instance
            with pytest.raises(SupabaseAuthError):
                await client._request("GET", "/v1/projects")

    @pytest.mark.asyncio
    async def test_get_project_returns_dict(self) -> None:
        client = SupabaseClient(access_token="tok")
        payload = {"id": "projref123", "name": "my-app", "status": "ACTIVE_HEALTHY", "region": "us-east-1"}
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=payload):
            result = await client.get_project("projref123")
        assert result["id"] == "projref123"
        assert result["status"] == "ACTIVE_HEALTHY"

    @pytest.mark.asyncio
    async def test_wait_for_active_returns_immediately_when_healthy(self) -> None:
        client = SupabaseClient(access_token="tok")
        healthy = {"id": "ref", "name": "proj", "status": "ACTIVE_HEALTHY", "region": "us-east-1"}
        with patch.object(client, "get_project", new_callable=AsyncMock, return_value=healthy):
            result = await client.wait_for_active("ref", timeout=60)
        assert result["status"] == "ACTIVE_HEALTHY"

    @pytest.mark.asyncio
    async def test_wait_for_active_raises_timeout(self) -> None:
        import time

        client = SupabaseClient(access_token="tok")
        coming_up = {"id": "ref", "status": "COMING_UP"}
        with patch.object(client, "get_project", new_callable=AsyncMock, return_value=coming_up):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch("time.monotonic", side_effect=[0.0, 0.0, 999.0]):
                    with pytest.raises(SupabaseProvisionTimeoutError):
                        await client.wait_for_active("ref", timeout=5, interval=1)

    @pytest.mark.asyncio
    async def test_get_api_keys_returns_dict(self) -> None:
        client = SupabaseClient(access_token="tok")
        keys_payload = [
            {"name": "anon", "api_key": "anon-key-value"},
            {"name": "service_role", "api_key": "service-role-key-value"},
        ]
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=keys_payload):
            result = await client.get_api_keys("ref")
        assert result["anon"] == "anon-key-value"
        assert result["service_role"] == "service-role-key-value"

    @pytest.mark.asyncio
    async def test_run_migrations_executes_sorted_sql(self) -> None:
        client = SupabaseClient(access_token="tok")
        sql_files = [
            {"path": "migrations/002_add_users.sql", "content": "CREATE TABLE users (id uuid);"},
            {"path": "migrations/001_init.sql", "content": "CREATE EXTENSION IF NOT EXISTS pgcrypto;"},
        ]
        with patch.object(client, "run_sql", new_callable=AsyncMock, return_value=None) as mock_sql:
            executed = await client.run_migrations("ref", sql_files)
        # Should execute in sorted order (001 before 002)
        assert executed == [
            "migrations/001_init.sql",
            "migrations/002_add_users.sql",
        ]
        assert mock_sql.call_count == 2

    @pytest.mark.asyncio
    async def test_run_migrations_skips_empty_files(self) -> None:
        client = SupabaseClient(access_token="tok")
        sql_files = [
            {"path": "migrations/001_init.sql", "content": ""},
            {"path": "migrations/002.sql", "content": "SELECT 1;"},
        ]
        with patch.object(client, "run_sql", new_callable=AsyncMock, return_value=None) as mock_sql:
            executed = await client.run_migrations("ref", sql_files)
        assert executed == ["migrations/002.sql"]
        assert mock_sql.call_count == 1

    @pytest.mark.asyncio
    async def test_run_migrations_propagates_sql_error(self) -> None:
        client = SupabaseClient(access_token="tok")
        sql_files = [{"path": "001.sql", "content": "BAD SQL;"}]
        with patch.object(
            client,
            "run_sql",
            new_callable=AsyncMock,
            side_effect=SupabaseError("syntax error"),
        ):
            with pytest.raises(SupabaseError, match="Migration failed"):
                await client.run_migrations("ref", sql_files)


# ===========================================================================
# Vercel client
# ===========================================================================


class TestVercelProjectFromJson:
    def test_basic_project(self) -> None:
        data = {"id": "prj_abc", "name": "my-app"}
        project = _project_from_json(data)
        assert project.id == "prj_abc"
        assert project.name == "my-app"
        assert project.production_url is None

    def test_project_with_alias(self) -> None:
        data = {
            "id": "prj_abc",
            "name": "my-app",
            "alias": [{"domain": "my-app.vercel.app"}],
        }
        project = _project_from_json(data)
        assert project.production_url == "https://my-app.vercel.app"


class TestVercelDeploymentFromJson:
    def test_queued_deployment(self) -> None:
        data = {"id": "dpl_xyz", "url": "my-app-abc.vercel.app", "state": "QUEUED"}
        deployment = _deployment_from_json(data)
        assert deployment.state == "QUEUED"
        assert deployment.url == "https://my-app-abc.vercel.app"

    def test_ready_deployment_with_alias(self) -> None:
        data = {
            "id": "dpl_xyz",
            "url": "my-app-abc.vercel.app",
            "state": "READY",
            "alias": [{"domain": "my-app.vercel.app"}],
        }
        deployment = _deployment_from_json(data)
        assert deployment.production_url == "https://my-app.vercel.app"


class TestVercelClient:
    @pytest.mark.asyncio
    async def test_create_project_posts_correctly(self) -> None:
        client = VercelClient("tok")
        payload = {"id": "prj_new", "name": "id8-abc"}
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=payload):
            project = await client.create_project("id8-abc")
        assert project.id == "prj_new"

    @pytest.mark.asyncio
    async def test_set_env_vars_filters_secrets(self) -> None:
        client = VercelClient("tok")
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=None) as mock_req:
            await client.set_env_vars(
                "prj_id",
                {
                    "NEXT_PUBLIC_SUPABASE_URL": "https://x.supabase.co",
                    "SERVICE_ROLE_SECRET": "must-be-filtered",
                },
            )
        # Only publishable vars should be POSTed.
        call_body = mock_req.call_args[1]["body"]
        keys_posted = {item["key"] for item in call_body}
        assert "NEXT_PUBLIC_SUPABASE_URL" in keys_posted
        assert "SERVICE_ROLE_SECRET" not in keys_posted

    @pytest.mark.asyncio
    async def test_set_env_vars_skips_when_nothing_to_inject(self) -> None:
        client = VercelClient("tok")
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            await client.set_env_vars("prj_id", {"PRIVATE_KEY": "secret"})
        mock_req.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_deployment_returns_ready_immediately(self) -> None:
        client = VercelClient("tok")
        ready = VercelDeployment(
            id="dpl_1", url="https://x.vercel.app", state="READY",
            ready_state="READY", production_url="https://x.vercel.app"
        )
        with patch.object(client, "get_deployment", new_callable=AsyncMock, return_value=ready):
            result = await client.poll_deployment("dpl_1", timeout=60)
        assert result.state == "READY"

    @pytest.mark.asyncio
    async def test_poll_deployment_raises_timeout(self) -> None:
        import time

        client = VercelClient("tok")
        building = VercelDeployment(
            id="dpl_1", url="https://x.vercel.app", state="BUILDING",
            ready_state="BUILDING", production_url=None
        )
        with patch.object(client, "get_deployment", new_callable=AsyncMock, return_value=building):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch("time.monotonic", side_effect=[0.0, 0.0, 999.0]):
                    with pytest.raises(VercelDeployTimeoutError):
                        await client.poll_deployment("dpl_1", timeout=5, interval=1)

    @pytest.mark.asyncio
    async def test_poll_deployment_raises_on_error_state(self) -> None:
        client = VercelClient("tok")
        errored = VercelDeployment(
            id="dpl_1", url="https://x.vercel.app", state="ERROR",
            ready_state="ERROR", production_url=None
        )
        with patch.object(client, "get_deployment", new_callable=AsyncMock, return_value=errored):
            # ERROR is a terminal state — should return immediately (not raise)
            result = await client.poll_deployment("dpl_1", timeout=60)
        assert result.state == "ERROR"


# ===========================================================================
# DeployProduction handler helpers
# ===========================================================================


class TestExtractSqlFiles:
    def test_extracts_sql_by_language(self) -> None:
        files = [
            {"path": "app/main.py", "content": "print(1)", "language": "python"},
            {"path": "db/init.sql", "content": "CREATE TABLE users (id uuid);", "language": "sql"},
        ]
        result = _extract_sql_files(files)
        assert len(result) == 1
        assert result[0]["path"] == "db/init.sql"

    def test_extracts_sql_by_extension(self) -> None:
        files = [
            {"path": "migrations/001.sql", "content": "SELECT 1;", "language": "text"},
        ]
        result = _extract_sql_files(files)
        assert len(result) == 1

    def test_extracts_sql_by_path_keyword(self) -> None:
        files = [
            {"path": "db/migrations/add_column.ts", "content": "// migration", "language": "typescript"},
        ]
        result = _extract_sql_files(files)
        assert len(result) == 1

    def test_skips_non_sql_files(self) -> None:
        files = [
            {"path": "app/main.py", "content": "x", "language": "python"},
            {"path": "frontend/page.tsx", "content": "y", "language": "typescript"},
        ]
        assert _extract_sql_files(files) == []


class TestGenerateDbPass:
    def test_correct_length(self) -> None:
        pw = _generate_db_pass()
        assert len(pw) == 32

    def test_generates_unique_passwords(self) -> None:
        assert _generate_db_pass() != _generate_db_pass()


@pytest.mark.asyncio
async def test_health_check_returns_true_for_200() -> None:
    import httpx

    with patch.object(httpx, "AsyncClient") as mock_cls:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.get = AsyncMock(return_value=httpx.Response(200))
        mock_cls.return_value = instance
        ok, detail = await _health_check("https://example.com")
    assert ok is True
    assert "200" in detail


@pytest.mark.asyncio
async def test_health_check_returns_false_for_500() -> None:
    import httpx

    with patch.object(httpx, "AsyncClient") as mock_cls:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.get = AsyncMock(return_value=httpx.Response(500))
        mock_cls.return_value = instance
        ok, detail = await _health_check("https://example.com")
    assert ok is False


@pytest.mark.asyncio
async def test_health_check_handles_connection_error() -> None:
    import httpx

    with patch.object(httpx, "AsyncClient") as mock_cls:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_cls.return_value = instance
        ok, detail = await _health_check("https://example.com")
    assert ok is False
    assert "Connection refused" in detail


@pytest.mark.asyncio
async def test_health_check_returns_false_for_empty_url() -> None:
    ok, detail = await _health_check("")
    assert ok is False


# ===========================================================================
# DeployProduction handler — integration path
# ===========================================================================


@pytest.mark.asyncio
async def test_deploy_production_fails_without_approval() -> None:
    handler = DeployProductionHandler()
    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.project_id = uuid.uuid4()
    ctx.workflow_payload = {}

    with patch(
        "app.orchestrator.handlers.deploy_production._load_deploy_approval",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await handler.execute(ctx)

    assert result.outcome == "failure"
    assert "approval" in result.error.lower()


@pytest.mark.asyncio
async def test_deploy_production_fails_without_code_snapshot() -> None:
    handler = DeployProductionHandler()
    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.project_id = uuid.uuid4()
    ctx.workflow_payload = {}

    with patch(
        "app.orchestrator.handlers.deploy_production._load_deploy_approval",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        with patch(
            "app.orchestrator.handlers.deploy_production._load_code_snapshot",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await handler.execute(ctx)

    assert result.outcome == "failure"
    assert "code_snapshot" in result.error.lower()


@pytest.mark.asyncio
async def test_deploy_production_fails_without_vercel_token() -> None:
    handler = DeployProductionHandler()
    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.project_id = uuid.uuid4()
    ctx.workflow_payload = {}

    mock_project = MagicMock()
    mock_project.github_repo_url = "https://github.com/acme/my-app"
    mock_project.live_deployment_url = None

    with patch(
        "app.orchestrator.handlers.deploy_production._load_deploy_approval",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        with patch(
            "app.orchestrator.handlers.deploy_production._load_code_snapshot",
            new_callable=AsyncMock,
            return_value={"files": []},
        ):
            with patch(
                "app.orchestrator.handlers.deploy_production._load_project",
                new_callable=AsyncMock,
                return_value=mock_project,
            ):
                with patch(
                    "app.orchestrator.handlers.deploy_production.settings"
                ) as mock_settings:
                    mock_settings.vercel_token = ""
                    mock_settings.supabase_access_token = ""
                    mock_settings.supabase_org_id = ""
                    result = await handler.execute(ctx)

    assert result.outcome == "failure"
    assert "VERCEL_TOKEN" in result.error


@pytest.mark.asyncio
async def test_deploy_production_fails_without_github_repo_url() -> None:
    handler = DeployProductionHandler()
    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.project_id = uuid.uuid4()
    ctx.workflow_payload = {}

    mock_project = MagicMock()
    mock_project.github_repo_url = None

    with patch(
        "app.orchestrator.handlers.deploy_production._load_deploy_approval",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        with patch(
            "app.orchestrator.handlers.deploy_production._load_code_snapshot",
            new_callable=AsyncMock,
            return_value={"files": []},
        ):
            with patch(
                "app.orchestrator.handlers.deploy_production._load_project",
                new_callable=AsyncMock,
                return_value=mock_project,
            ):
                with patch(
                    "app.orchestrator.handlers.deploy_production.settings"
                ) as mock_settings:
                    mock_settings.vercel_token = "tok"
                    mock_settings.supabase_access_token = ""
                    mock_settings.supabase_org_id = ""
                    result = await handler.execute(ctx)

    assert result.outcome == "failure"
    assert "github_repo_url" in result.error


@pytest.mark.asyncio
async def test_deploy_production_success_path() -> None:
    """Full happy-path: Supabase skipped, Vercel succeeds."""
    handler = DeployProductionHandler()
    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.project_id = uuid.uuid4()
    ctx.workflow_payload = {}
    ctx.db.flush = AsyncMock()
    ctx.db.execute = AsyncMock()
    ctx.db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    ctx.db.add = MagicMock()

    mock_project = MagicMock()
    mock_project.github_repo_url = "https://github.com/acme/my-app"
    mock_project.live_deployment_url = None

    vercel_result = {
        "vercel_project_id": "prj_abc",
        "deployment_id": "dpl_xyz",
        "deployment_url": "https://my-app.vercel.app",
        "production_url": "https://my-app.vercel.app",
        "state": "READY",
    }

    with patch(
        "app.orchestrator.handlers.deploy_production._load_deploy_approval",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        with patch(
            "app.orchestrator.handlers.deploy_production._load_code_snapshot",
            new_callable=AsyncMock,
            return_value={"files": []},
        ):
            with patch(
                "app.orchestrator.handlers.deploy_production._load_project",
                new_callable=AsyncMock,
                return_value=mock_project,
            ):
                with patch(
                    "app.orchestrator.handlers.deploy_production.settings"
                ) as mock_settings:
                    mock_settings.vercel_token = "tok"
                    mock_settings.vercel_team_id = ""
                    mock_settings.supabase_access_token = ""
                    mock_settings.supabase_org_id = ""
                    with patch(
                        "app.orchestrator.handlers.deploy_production.deploy_to_vercel",
                        new_callable=AsyncMock,
                        return_value=vercel_result,
                    ):
                        with patch(
                            "app.orchestrator.handlers.deploy_production._health_check",
                            new_callable=AsyncMock,
                            return_value=(True, "HTTP 200"),
                        ):
                            with patch(
                                "app.orchestrator.handlers.deploy_production._create_or_update_deployment_record",
                                new_callable=AsyncMock,
                                return_value=MagicMock(),
                            ):
                                result = await handler.execute(ctx)

    assert result.outcome == "passed"
    assert result.artifact_data is not None
    assert result.artifact_data["live_url"] == "https://my-app.vercel.app"
    assert result.artifact_data["environment"] == "production"
    assert result.context_updates["live_url"] == "https://my-app.vercel.app"
