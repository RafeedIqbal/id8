"""Tests for the GitHub client and PreparePR handler.

All GitHub HTTP traffic is intercepted with httpx.MockTransport so no live
API calls are made.
"""
from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from app.github.auth import GitHubAuth
from app.github.client import (
    BranchRef,
    CheckRun,
    GitHubAuthError,
    GitHubChecksTimedOutError,
    GitHubClient,
    GitHubConflictError,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    MergeResult,
    PrInfo,
    RepoInfo,
    _generate_github_app_jwt,
    _parse_owner_repo,
)
from app.orchestrator.handlers.prepare_pr import (
    PreparePRHandler,
    _build_pr_title,
    _create_project_repo,
    _find_closed_pull_request,
    _generate_repo_name,
    _run_github_flow,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PAT_AUTH = GitHubAuth(mode="token", token="ghp_test_token")


def _make_mock_transport(responses: list[dict[str, Any]]) -> httpx.MockTransport:
    """Return a MockTransport that replays *responses* in order."""
    calls: list[dict[str, Any]] = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if not calls:
            return httpx.Response(500, json={"message": "unexpected request"})
        resp = calls.pop(0)
        return httpx.Response(
            resp.get("status", 200),
            json=resp.get("json"),
            headers=resp.get("headers", {}),
        )

    return httpx.MockTransport(handler)


def _client(responses: list[dict[str, Any]]) -> GitHubClient:
    """Build a GitHubClient whose underlying httpx.AsyncClient uses *responses*."""
    client = GitHubClient(PAT_AUTH)
    mock_transport = _make_mock_transport(responses)

    # Patch httpx.AsyncClient to use the mock transport.
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, **kwargs: Any) -> None:
        kwargs["transport"] = mock_transport
        original_init(self, **kwargs)

    client._patched_init = patched_init  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# _parse_owner_repo
# ---------------------------------------------------------------------------


def test_parse_owner_repo_https() -> None:
    owner, repo = _parse_owner_repo("https://github.com/acme/my-app")
    assert owner == "acme"
    assert repo == "my-app"


def test_parse_owner_repo_git_suffix() -> None:
    owner, repo = _parse_owner_repo("https://github.com/acme/my-app.git")
    assert owner == "acme"
    assert repo == "my-app"


def test_parse_owner_repo_trailing_slash() -> None:
    owner, repo = _parse_owner_repo("https://github.com/acme/my-app/")
    assert owner == "acme"
    assert repo == "my-app"


def test_parse_owner_repo_invalid_raises() -> None:
    with pytest.raises(GitHubError):
        _parse_owner_repo("not-a-github-url")


# ---------------------------------------------------------------------------
# _generate_repo_name
# ---------------------------------------------------------------------------


def test_generate_repo_name_format() -> None:
    project_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    name = _generate_repo_name(project_id)
    assert name.startswith("id8-")
    assert len(name) == len("id8-") + 12  # 12 hex chars


# ---------------------------------------------------------------------------
# GitHubClient._request — error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_raises_auth_error_on_401() -> None:
    """_request should raise GitHubAuthError for a 401 response."""
    client = GitHubClient(PAT_AUTH)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    with patch.object(httpx, "AsyncClient") as mock_cls:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.request = AsyncMock(return_value=httpx.Response(401, json={"message": "Bad credentials"}))
        mock_cls.return_value = instance

        with pytest.raises(GitHubAuthError):
            await client._request("GET", "/user")


@pytest.mark.asyncio
async def test_request_raises_not_found_on_404() -> None:
    client = GitHubClient(PAT_AUTH)

    with patch.object(httpx, "AsyncClient") as mock_cls:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.request = AsyncMock(return_value=httpx.Response(404, json={"message": "Not Found"}))
        mock_cls.return_value = instance

        with pytest.raises(GitHubNotFoundError):
            await client._request("GET", "/repos/a/b")


@pytest.mark.asyncio
async def test_request_raises_conflict_on_409() -> None:
    client = GitHubClient(PAT_AUTH)

    with patch.object(httpx, "AsyncClient") as mock_cls:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.request = AsyncMock(return_value=httpx.Response(409, json={"message": "Conflict"}))
        mock_cls.return_value = instance

        with pytest.raises(GitHubConflictError):
            await client._request("POST", "/repos/a/b/git/refs")


@pytest.mark.asyncio
async def test_request_raises_rate_limit_after_retries() -> None:
    """After all retry attempts, a 429 should raise GitHubRateLimitError."""
    client = GitHubClient(PAT_AUTH)
    rate_limited_resp = httpx.Response(
        429,
        json={"message": "rate limited"},
        headers={"Retry-After": "1"},
    )

    with patch.object(httpx, "AsyncClient") as mock_cls:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.request = AsyncMock(return_value=rate_limited_resp)
        mock_cls.return_value = instance

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(GitHubRateLimitError):
                await client._request("GET", "/repos/a/b")


@pytest.mark.asyncio
async def test_request_treats_403_rate_limit_as_rate_limit_error() -> None:
    client = GitHubClient(PAT_AUTH)
    rate_limited_resp = httpx.Response(
        403,
        json={"message": "You have exceeded a secondary rate limit."},
        headers={"Retry-After": "1"},
    )

    with patch.object(httpx, "AsyncClient") as mock_cls:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        instance.request = AsyncMock(return_value=rate_limited_resp)
        mock_cls.return_value = instance

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(GitHubRateLimitError):
                await client._request("GET", "/repos/a/b")


# ---------------------------------------------------------------------------
# GitHubClient.get_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_repo_returns_repo_info() -> None:
    client = GitHubClient(PAT_AUTH)
    repo_payload = {
        "name": "my-repo",
        "full_name": "acme/my-repo",
        "html_url": "https://github.com/acme/my-repo",
        "clone_url": "https://github.com/acme/my-repo.git",
        "private": True,
        "default_branch": "main",
    }

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = repo_payload
        info = await client.get_repo("acme", "my-repo")

    assert isinstance(info, RepoInfo)
    assert info.name == "my-repo"
    assert info.full_name == "acme/my-repo"
    assert info.default_branch == "main"


# ---------------------------------------------------------------------------
# GitHubClient.create_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_repo_posts_to_user_repos() -> None:
    client = GitHubClient(PAT_AUTH)
    repo_payload = {
        "name": "id8-abc123",
        "full_name": "user/id8-abc123",
        "html_url": "https://github.com/user/id8-abc123",
        "clone_url": "https://github.com/user/id8-abc123.git",
        "private": True,
        "default_branch": "main",
    }

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = repo_payload
        info = await client.create_repo("id8-abc123", private=True)

    mock_req.assert_called_once()
    call_args = mock_req.call_args
    assert call_args[0][0] == "POST"
    assert call_args[0][1] == "/user/repos"
    assert call_args[1]["body"]["auto_init"] is True
    assert isinstance(info, RepoInfo)


@pytest.mark.asyncio
async def test_create_repo_uses_org_path_when_provided() -> None:
    client = GitHubClient(PAT_AUTH)
    repo_payload = {
        "name": "id8-abc",
        "full_name": "my-org/id8-abc",
        "html_url": "https://github.com/my-org/id8-abc",
        "clone_url": "https://github.com/my-org/id8-abc.git",
        "private": True,
        "default_branch": "main",
    }

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = repo_payload
        await client.create_repo("id8-abc", org="my-org", private=True)

    assert mock_req.call_args[0][1] == "/orgs/my-org/repos"


# ---------------------------------------------------------------------------
# GitHubClient.create_branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_branch_uses_base_sha() -> None:
    client = GitHubClient(PAT_AUTH)
    base_ref_resp = {"object": {"sha": "abc123base"}}
    branch_resp = {"object": {"sha": "abc123branch"}}

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = [base_ref_resp, branch_resp]
        ref = await client.create_branch("owner", "repo", "main", "id8/run-xyz")

    assert isinstance(ref, BranchRef)
    assert ref.name == "id8/run-xyz"
    assert ref.sha == "abc123branch"
    # Second call should POST to refs with the base SHA in body.
    create_call = mock_req.call_args_list[1]
    assert create_call[1]["body"]["sha"] == "abc123base"


# ---------------------------------------------------------------------------
# GitHubClient.push_files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_files_returns_commit_sha() -> None:
    client = GitHubClient(PAT_AUTH)

    responses = [
        # GET branch ref
        {"object": {"sha": "head-sha"}},
        # GET commit
        {"tree": {"sha": "tree-sha"}},
        # POST blob for file 1
        {"sha": "blob-sha-1"},
        # POST blob for file 2
        {"sha": "blob-sha-2"},
        # POST tree
        {"sha": "new-tree-sha"},
        # POST commit
        {"sha": "new-commit-sha"},
        # PATCH ref
        None,
    ]

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = responses
        commit_sha = await client.push_files(
            "owner",
            "repo",
            "id8/run-123",
            [
                {"path": "app/main.py", "content": "print('hello')"},
                {"path": "README.md", "content": "# Hello"},
            ],
        )

    assert commit_sha == "new-commit-sha"
    # Verify the ref was updated.
    patch_call = mock_req.call_args_list[-1]
    assert patch_call[0][0] == "PATCH"
    assert patch_call[1]["body"]["sha"] == "new-commit-sha"


@pytest.mark.asyncio
async def test_push_files_rejects_protected_default_branch() -> None:
    client = GitHubClient(PAT_AUTH)

    with pytest.raises(GitHubConflictError, match="Direct pushes to protected branch"):
        await client.push_files(
            "owner",
            "repo",
            "main",
            [{"path": "README.md", "content": "# hello"}],
        )


# ---------------------------------------------------------------------------
# GitHubClient.list_pull_requests / create_pull_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pull_requests_returns_pr_list() -> None:
    client = GitHubClient(PAT_AUTH)
    pr_payload = [
        {
            "number": 42,
            "html_url": "https://github.com/owner/repo/pull/42",
            "state": "open",
            "head": {"sha": "pr-head-sha"},
            "title": "feat: hello",
        }
    ]

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = pr_payload
        prs = await client.list_pull_requests("owner", "repo")

    assert len(prs) == 1
    assert isinstance(prs[0], PrInfo)
    assert prs[0].number == 42


@pytest.mark.asyncio
async def test_create_pull_request_posts_correct_body() -> None:
    client = GitHubClient(PAT_AUTH)
    pr_payload = {
        "number": 7,
        "html_url": "https://github.com/owner/repo/pull/7",
        "state": "open",
        "head": {"sha": "abc"},
        "title": "feat(id8): my feature",
    }

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = pr_payload
        pr = await client.create_pull_request(
            "owner", "repo", head="feature-branch", base="main", title="feat(id8): my feature", body="body text"
        )

    assert pr.number == 7
    call_body = mock_req.call_args[1]["body"]
    assert call_body["head"] == "feature-branch"
    assert call_body["base"] == "main"


# ---------------------------------------------------------------------------
# GitHubClient.get_check_runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_check_runs_returns_list() -> None:
    client = GitHubClient(PAT_AUTH)
    payload = {
        "check_runs": [
            {
                "id": 1,
                "name": "ci/build",
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/owner/repo/runs/1",
            },
            {
                "id": 2,
                "name": "ci/lint",
                "status": "in_progress",
                "conclusion": None,
                "html_url": "https://github.com/owner/repo/runs/2",
            },
        ]
    }

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = payload
        runs = await client.get_check_runs("owner", "repo", "abc123")

    assert len(runs) == 2
    assert isinstance(runs[0], CheckRun)
    assert runs[0].conclusion == "success"
    assert runs[1].status == "in_progress"
    assert mock_req.call_args.args[0] == "GET"
    assert mock_req.call_args.args[1] == "/repos/owner/repo/commits/abc123/check-runs"
    assert mock_req.call_args.kwargs["params"] == {"per_page": "100"}


# ---------------------------------------------------------------------------
# GitHubClient.poll_checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_checks_returns_immediately_when_all_complete() -> None:
    client = GitHubClient(PAT_AUTH)
    completed_runs = [
        CheckRun(id=1, name="ci/build", status="completed", conclusion="success", html_url=""),
    ]

    with patch.object(client, "get_check_runs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = completed_runs
        result = await client.poll_checks("owner", "repo", "sha123", timeout=60)

    assert result == completed_runs
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_poll_checks_returns_empty_when_no_checks() -> None:
    client = GitHubClient(PAT_AUTH)

    with patch.object(client, "get_check_runs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = []
        result = await client.poll_checks("owner", "repo", "sha123", timeout=60)

    assert result == []


@pytest.mark.asyncio
async def test_poll_checks_raises_timeout_when_still_pending() -> None:
    client = GitHubClient(PAT_AUTH)
    pending_run = CheckRun(id=1, name="ci/slow", status="in_progress", conclusion=None, html_url="")

    with patch.object(client, "get_check_runs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = [pending_run]
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("time.monotonic", side_effect=[0.0, 0.0, 999.0]):
                with pytest.raises(GitHubChecksTimedOutError):
                    await client.poll_checks("owner", "repo", "sha123", timeout=5, interval=1)


# ---------------------------------------------------------------------------
# GitHubClient.merge_pull_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_pull_request_returns_merge_result() -> None:
    client = GitHubClient(PAT_AUTH)
    payload = {
        "sha": "merge-sha-abc",
        "merged": True,
        "message": "Pull request successfully merged",
    }

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = payload
        result = await client.merge_pull_request("owner", "repo", 42)

    assert isinstance(result, MergeResult)
    assert result.sha == "merge-sha-abc"
    assert result.merged is True
    call_body = mock_req.call_args[1]["body"]
    assert call_body["merge_method"] == "squash"


# ---------------------------------------------------------------------------
# GitHubClient.auth_header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_header_token_mode() -> None:
    client = GitHubClient(GitHubAuth(mode="token", token="my-pat"))
    header = await client._auth_header()
    assert header == {"Authorization": "Bearer my-pat"}


@pytest.mark.asyncio
async def test_auth_header_none_mode() -> None:
    client = GitHubClient(GitHubAuth(mode="none"))
    header = await client._auth_header()
    assert header == {}


# ---------------------------------------------------------------------------
# _build_pr_title
# ---------------------------------------------------------------------------


def test_build_pr_title_uses_prompt() -> None:
    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.workflow_payload = {"initial_prompt": "Build me a todo app"}
    title = _build_pr_title(ctx)
    assert "Build me a todo app" in title
    assert title.startswith("feat(id8):")


def test_build_pr_title_truncates_long_prompt() -> None:
    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.workflow_payload = {"initial_prompt": "x" * 200}
    title = _build_pr_title(ctx)
    assert len(title) <= 90  # reasonable upper bound


def test_build_pr_title_falls_back_to_run_id() -> None:
    ctx = MagicMock()
    run_id = uuid.uuid4()
    ctx.run_id = run_id
    ctx.workflow_payload = {}
    title = _build_pr_title(ctx)
    assert str(run_id) in title


# ---------------------------------------------------------------------------
# _create_project_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_project_repo_creates_public_repo() -> None:
    ctx = MagicMock()
    ctx.project_id = uuid.uuid4()
    ctx.run_id = uuid.uuid4()
    ctx.db = MagicMock()
    ctx.db.flush = AsyncMock()

    project = MagicMock()
    project.github_repo_url = None

    client = MagicMock()
    client.get_authenticated_user = AsyncMock(return_value={"login": "RafeedIqbal"})
    client.create_repo = AsyncMock(
        return_value=RepoInfo(
            name="id8-abc123",
            full_name="RafeedIqbal/id8-abc123",
            html_url="https://github.com/RafeedIqbal/id8-abc123",
            clone_url="https://github.com/RafeedIqbal/id8-abc123.git",
            private=False,
            default_branch="main",
        )
    )

    with patch("app.orchestrator.handlers.prepare_pr.emit_audit_event", new=AsyncMock()):
        owner, repo_name = await _create_project_repo(ctx, client, project)

    assert owner == "RafeedIqbal"
    assert repo_name == "id8-abc123"
    assert project.github_repo_url == "https://github.com/RafeedIqbal/id8-abc123"
    assert client.create_repo.await_args.kwargs["private"] is False
    ctx.db.flush.assert_awaited()


# ---------------------------------------------------------------------------
# _run_github_flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_github_flow_recreates_repo_when_stored_repo_missing() -> None:
    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.project_id = uuid.uuid4()
    ctx.workflow_payload = {"initial_prompt": "Create app"}
    ctx.db = MagicMock()

    project = MagicMock()
    project.github_repo_url = "https://github.com/RafeedIqbal/id8-a22ad2deb369"

    client = MagicMock()
    client.push_files = AsyncMock(return_value="commit-sha")
    client.poll_checks = AsyncMock(
        return_value=[
            CheckRun(
                id=1,
                name="ci/test",
                status="completed",
                conclusion="success",
                html_url="https://github.com/RafeedIqbal/id8/actions/runs/1",
            )
        ]
    )
    client.merge_pull_request = AsyncMock(
        return_value=MergeResult(sha="merge-sha", merged=True, message="merged")
    )

    pr_info = PrInfo(
        number=11,
        html_url="https://github.com/RafeedIqbal/id8-a22ad2deb369/pull/11",
        state="open",
        head_sha="head-sha",
        title="feat(id8): Create app",
    )

    async def _fake_create_repo(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        project.github_repo_url = "https://github.com/RafeedIqbal/id8-a22ad2deb369"
        return "RafeedIqbal", "id8-a22ad2deb369"

    with (
        patch("app.orchestrator.handlers.prepare_pr._load_project", new=AsyncMock(return_value=project)),
        patch(
            "app.orchestrator.handlers.prepare_pr._create_project_repo",
            new=AsyncMock(side_effect=_fake_create_repo),
        ) as mock_create_repo,
        patch(
            "app.orchestrator.handlers.prepare_pr._ensure_branch",
            new=AsyncMock(side_effect=[GitHubNotFoundError("missing"), "main"]),
        ) as mock_ensure_branch,
        patch("app.orchestrator.handlers.prepare_pr._find_closed_pull_request", new=AsyncMock(return_value=None)),
        patch("app.orchestrator.handlers.prepare_pr._ensure_pull_request", new=AsyncMock(return_value=pr_info)),
        patch("app.orchestrator.handlers.prepare_pr._persist_prepare_pr_metadata", new=AsyncMock()),
        patch("app.orchestrator.handlers.prepare_pr.emit_audit_event", new=AsyncMock()),
    ):
        result = await _run_github_flow(
            ctx,
            client,
            files=[{"path": "README.md", "content": "# generated"}],
        )

    assert result.outcome == "success"
    assert mock_create_repo.await_count == 1
    assert mock_ensure_branch.await_count == 2
    assert result.context_updates is not None
    assert result.context_updates["github_repo_url"] == "https://github.com/RafeedIqbal/id8-a22ad2deb369"
    push_args = client.push_files.await_args.args
    assert push_args[0] == "RafeedIqbal"
    assert push_args[1] == "id8-a22ad2deb369"


@pytest.mark.asyncio
async def test_run_github_flow_continues_when_check_run_permissions_missing() -> None:
    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.project_id = uuid.uuid4()
    ctx.workflow_payload = {"initial_prompt": "Create app"}
    ctx.db = MagicMock()

    project = MagicMock()
    project.github_repo_url = "https://github.com/RafeedIqbal/id8-a22ad2deb369"

    client = MagicMock()
    client.push_files = AsyncMock(return_value="commit-sha")
    client.poll_checks = AsyncMock(side_effect=GitHubAuthError("403 Forbidden"))
    client.merge_pull_request = AsyncMock(
        return_value=MergeResult(sha="merge-sha", merged=True, message="merged")
    )

    pr_info = PrInfo(
        number=12,
        html_url="https://github.com/RafeedIqbal/id8-a22ad2deb369/pull/12",
        state="open",
        head_sha="head-sha",
        title="feat(id8): Create app",
    )

    with (
        patch("app.orchestrator.handlers.prepare_pr._load_project", new=AsyncMock(return_value=project)),
        patch("app.orchestrator.handlers.prepare_pr._ensure_branch", new=AsyncMock(return_value="main")),
        patch("app.orchestrator.handlers.prepare_pr._find_closed_pull_request", new=AsyncMock(return_value=None)),
        patch("app.orchestrator.handlers.prepare_pr._ensure_pull_request", new=AsyncMock(return_value=pr_info)),
        patch("app.orchestrator.handlers.prepare_pr._persist_prepare_pr_metadata", new=AsyncMock()),
        patch("app.orchestrator.handlers.prepare_pr.emit_audit_event", new=AsyncMock()),
    ):
        result = await _run_github_flow(
            ctx,
            client,
            files=[{"path": "README.md", "content": "# generated"}],
        )

    assert result.outcome == "success"
    client.merge_pull_request.assert_awaited_once()
    assert result.context_updates is not None
    assert result.context_updates["check_statuses"] == []


# ---------------------------------------------------------------------------
# _find_closed_pull_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_closed_pull_request_returns_none_when_no_prs() -> None:
    client = GitHubClient(PAT_AUTH)
    with patch.object(client, "list_pull_requests", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = []
        result = await _find_closed_pull_request(client, "owner", "repo", "id8/run-1")
    assert result is None


@pytest.mark.asyncio
async def test_find_closed_pull_request_ignores_when_open_exists() -> None:
    client = GitHubClient(PAT_AUTH)
    open_pr = PrInfo(
        number=1,
        html_url="https://github.com/owner/repo/pull/1",
        state="open",
        head_sha="head",
        title="open",
    )
    with patch.object(client, "list_pull_requests", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [open_pr]
        result = await _find_closed_pull_request(client, "owner", "repo", "id8/run-1")
    assert result is None


@pytest.mark.asyncio
async def test_find_closed_pull_request_returns_merged_pr_when_present() -> None:
    client = GitHubClient(PAT_AUTH)
    closed_unmerged = PrInfo(
        number=2,
        html_url="https://github.com/owner/repo/pull/2",
        state="closed",
        head_sha="head2",
        title="closed",
    )
    closed_merged = PrInfo(
        number=3,
        html_url="https://github.com/owner/repo/pull/3",
        state="closed",
        head_sha="head3",
        title="merged",
        merged=True,
        merge_commit_sha="merge-sha",
    )
    with patch.object(client, "list_pull_requests", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [closed_unmerged, closed_merged]
        result = await _find_closed_pull_request(client, "owner", "repo", "id8/run-1")
    assert result is not None
    assert result.number == 3
    assert result.merged is True


# ---------------------------------------------------------------------------
# PreparePRHandler — failure cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_pr_handler_fails_without_credentials() -> None:
    handler = PreparePRHandler()

    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.project_id = uuid.uuid4()
    ctx.workflow_payload = {}

    # Patch code snapshot loading to return something valid.
    with patch(
        "app.orchestrator.handlers.prepare_pr._load_code_snapshot",
        new_callable=AsyncMock,
        return_value={"files": [{"path": "main.py", "content": "print(1)"}]},
    ):
        with patch("app.orchestrator.handlers.prepare_pr.resolve_github_auth") as mock_auth:
            from app.github.auth import GitHubAuth

            mock_auth.return_value = GitHubAuth(mode="none")
            result = await handler.execute(ctx)

    assert result.outcome == "failure"
    assert "credentials" in result.error.lower()


@pytest.mark.asyncio
async def test_prepare_pr_handler_fails_when_no_code_snapshot() -> None:
    handler = PreparePRHandler()

    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.project_id = uuid.uuid4()
    ctx.workflow_payload = {}

    with patch(
        "app.orchestrator.handlers.prepare_pr._load_code_snapshot",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await handler.execute(ctx)

    assert result.outcome == "failure"
    assert "code_snapshot" in result.error


@pytest.mark.asyncio
async def test_prepare_pr_handler_fails_when_snapshot_has_no_files() -> None:
    handler = PreparePRHandler()

    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.project_id = uuid.uuid4()
    ctx.workflow_payload = {}

    with patch(
        "app.orchestrator.handlers.prepare_pr._load_code_snapshot",
        new_callable=AsyncMock,
        return_value={"files": []},
    ):
        result = await handler.execute(ctx)

    assert result.outcome == "failure"
    assert "no files" in result.error.lower()


@pytest.mark.asyncio
async def test_prepare_pr_handler_raises_rate_limit_error() -> None:
    """GitHubRateLimitError from the client should surface as RateLimitError."""
    from app.orchestrator.retry import RateLimitError

    handler = PreparePRHandler()

    ctx = MagicMock()
    ctx.run_id = uuid.uuid4()
    ctx.project_id = uuid.uuid4()
    ctx.workflow_payload = {}

    with patch(
        "app.orchestrator.handlers.prepare_pr._load_code_snapshot",
        new_callable=AsyncMock,
        return_value={"files": [{"path": "main.py", "content": "x"}]},
    ):
        with patch("app.orchestrator.handlers.prepare_pr.resolve_github_auth") as mock_auth:
            from app.github.auth import GitHubAuth

            mock_auth.return_value = GitHubAuth(mode="token", token="tok")

            with patch(
                "app.orchestrator.handlers.prepare_pr._run_github_flow",
                new_callable=AsyncMock,
                side_effect=GitHubRateLimitError("rate limited", retry_after=30.0),
            ):
                with pytest.raises(RateLimitError):
                    await handler.execute(ctx)
