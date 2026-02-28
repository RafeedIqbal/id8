"""GitHub REST API client for ID8.

Provides a thin async wrapper around GitHub API v3 with:
- PAT and GitHub App authentication
- Repo, branch, and pull-request management
- Git Data API file pushes (blob/tree/commit/ref flow)
- Check run polling
- Exponential backoff on rate limits
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote

import httpx

from app.github.auth import GitHubAuth

logger = logging.getLogger("id8.github.client")

_BASE_URL = "https://api.github.com"
_MAX_RETRIES = 5
_BASE_BACKOFF = 1.0
_CHECK_POLL_INTERVAL = 15.0
_CHECK_POLL_TIMEOUT = 600.0  # 10 minutes default


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RepoInfo:
    name: str
    full_name: str
    html_url: str
    clone_url: str
    private: bool
    default_branch: str


@dataclass(frozen=True, slots=True)
class BranchRef:
    name: str
    sha: str


@dataclass(frozen=True, slots=True)
class PrInfo:
    number: int
    html_url: str
    state: str
    head_sha: str
    title: str
    merged: bool = False
    merge_commit_sha: str | None = None


@dataclass(frozen=True, slots=True)
class CheckRun:
    id: int
    name: str
    status: str  # "queued" | "in_progress" | "completed"
    conclusion: str | None  # "success" | "failure" | "cancelled" | …
    html_url: str


@dataclass(frozen=True, slots=True)
class MergeResult:
    sha: str
    merged: bool
    message: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GitHubError(Exception):
    """Base error for GitHub API failures."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubAuthError(GitHubError):
    """Authentication or authorization failure (401 / 403)."""


class GitHubRateLimitError(GitHubError):
    """Rate limit exceeded (429)."""

    def __init__(self, message: str, *, retry_after: float = 60.0) -> None:
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class GitHubNotFoundError(GitHubError):
    """Resource not found (404)."""


class GitHubConflictError(GitHubError):
    """Conflict, e.g. branch already exists (409 / 422)."""


class GitHubChecksTimedOutError(GitHubError):
    """Check-run polling timed out before all checks completed."""


# ---------------------------------------------------------------------------
# JWT helper (GitHub App auth)
# ---------------------------------------------------------------------------


def _generate_github_app_jwt(app_id: str, private_key_pem: str) -> str:
    """Generate a short-lived JWT for GitHub App authentication.

    Requires ``PyJWT[cryptography]``.  The dependency is intentionally lazy
    since PAT auth (the MVP default) does not need it.
    """
    try:
        import jwt as _jwt  # type: ignore[import-not-found]  # PyJWT
    except ImportError as exc:
        raise ImportError(
            "PyJWT[cryptography] is required for GitHub App authentication. "
            "Install it with: pip install 'PyJWT[cryptography]'"
        ) from exc

    now = int(time.time())
    payload: dict[str, Any] = {
        "iat": now - 60,  # issued-at: 60 s in the past to absorb clock skew
        "exp": now + 600,  # valid for 10 minutes
        "iss": app_id,
    }
    return str(_jwt.encode(payload, private_key_pem, algorithm="RS256"))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GitHubClient:
    """Async GitHub REST API client."""

    def __init__(self, auth: GitHubAuth) -> None:
        self._auth = auth

    # ------------------------------------------------------------------
    # Auth header resolution
    # ------------------------------------------------------------------

    async def _auth_header(self) -> dict[str, str]:
        if self._auth.mode == "token":
            return {"Authorization": f"Bearer {self._auth.token}"}
        if self._auth.mode == "app":
            token = await self._get_app_installation_token()
            return {"Authorization": f"Bearer {token}"}
        return {}

    async def _get_app_installation_token(self) -> str:
        assert self._auth.app_id is not None  # guarded by resolve_github_auth
        assert self._auth.app_private_key is not None
        jwt_token = _generate_github_app_jwt(self._auth.app_id, self._auth.app_private_key)
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(f"{_BASE_URL}/app/installations", headers=headers)
            resp.raise_for_status()
            installations: list[dict[str, Any]] = resp.json()
            if not installations:
                raise GitHubAuthError("No GitHub App installations found")
            installation_id: int = installations[0]["id"]

            resp = await http.post(
                f"{_BASE_URL}/app/installations/{installation_id}/access_tokens",
                headers=headers,
            )
            resp.raise_for_status()
            return str(resp.json()["token"])

    # ------------------------------------------------------------------
    # Low-level request with rate-limit backoff
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        url = f"{_BASE_URL}{path}"
        auth_hdr = await self._auth_header()
        headers = {
            **auth_hdr,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        for attempt in range(_MAX_RETRIES):
            async with httpx.AsyncClient(timeout=30) as http:
                resp = await http.request(method, url, headers=headers, json=body, params=params)

            if _is_rate_limit_response(resp):
                retry_after = _compute_retry_after_seconds(resp, attempt)
                if attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "GitHub rate limit hit, retrying after %.1f s (attempt %d/%d)",
                        retry_after,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                raise GitHubRateLimitError(
                    "GitHub API rate limit exceeded",
                    retry_after=retry_after,
                )

            if resp.status_code in (401, 403):
                raise GitHubAuthError(
                    f"GitHub authentication failed ({resp.status_code}): {resp.text}",
                    status_code=resp.status_code,
                )

            if resp.status_code == 404:
                raise GitHubNotFoundError(
                    f"GitHub resource not found: {path}",
                    status_code=404,
                )

            if resp.status_code in (409, 422):
                raise GitHubConflictError(
                    f"GitHub conflict ({resp.status_code}): {resp.text}",
                    status_code=resp.status_code,
                )

            if resp.status_code >= 400:
                raise GitHubError(
                    f"GitHub API error {resp.status_code}: {resp.text}",
                    status_code=resp.status_code,
                )

            if resp.status_code == 204:
                return None

            return resp.json()
        raise GitHubError("GitHub request exhausted retries without a response")

    # ------------------------------------------------------------------
    # User / org helpers
    # ------------------------------------------------------------------

    async def get_authenticated_user(self) -> dict[str, Any]:
        """Return the authenticated user's login and metadata."""
        return cast(dict[str, Any], await self._request("GET", "/user"))

    # ------------------------------------------------------------------
    # Repository
    # ------------------------------------------------------------------

    async def get_repo(self, owner: str, repo: str) -> RepoInfo:
        """Fetch an existing repository."""
        data = cast(dict[str, Any], await self._request("GET", f"/repos/{owner}/{repo}"))
        return _repo_from_json(data)

    async def create_repo(
        self,
        name: str,
        *,
        org: str | None = None,
        private: bool = True,
    ) -> RepoInfo:
        """Create a new repository.

        If *org* is provided the repo is created under that org, otherwise
        under the authenticated user.  Always uses ``auto_init=True`` so the
        default branch exists before any branch operations.
        """
        body: dict[str, Any] = {
            "name": name,
            "private": private,
            "auto_init": True,
        }
        path = f"/orgs/{org}/repos" if org else "/user/repos"
        data = cast(dict[str, Any], await self._request("POST", path, body=body))
        return _repo_from_json(data)

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    async def get_branch(self, owner: str, repo: str, branch: str) -> BranchRef:
        """Return the branch ref for *branch*.  Raises GitHubNotFoundError if absent."""
        data = cast(dict[str, Any], await self._request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}"))
        sha: str = data["object"]["sha"]
        return BranchRef(name=branch, sha=sha)

    async def create_branch(self, owner: str, repo: str, base: str, branch_name: str) -> BranchRef:
        """Create *branch_name* branching off *base*.

        Returns the new ref.  Raises GitHubConflictError if the branch already
        exists (caller should treat this as idempotent success).
        """
        # Resolve base ref SHA first
        base_ref = cast(dict[str, Any], await self._request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{base}"))
        base_sha: str = base_ref["object"]["sha"]

        body: dict[str, Any] = {"ref": f"refs/heads/{branch_name}", "sha": base_sha}
        data = cast(dict[str, Any], await self._request("POST", f"/repos/{owner}/{repo}/git/refs", body=body))
        sha: str = data["object"]["sha"]
        return BranchRef(name=branch_name, sha=sha)

    # ------------------------------------------------------------------
    # File push via Git Data API
    # ------------------------------------------------------------------

    async def push_files(
        self,
        owner: str,
        repo: str,
        branch: str,
        files: list[dict[str, str]],
        commit_message: str = "chore: id8 generated code",
        authoritative: bool = False,
    ) -> str:
        """Push *files* to *branch* as a single commit.

        *files* is a list of ``{"path": str, "content": str}`` dicts.

        Returns the new commit SHA.

        Uses the Git Data API (blob → tree → commit → update ref) so it
        works without a local git clone.
        """
        if branch in {"main", "master"}:
            raise GitHubConflictError(
                f"Direct pushes to protected branch '{branch}' are not allowed",
                status_code=409,
            )

        # 1. Get the current HEAD commit for the branch.
        ref_data = cast(dict[str, Any], await self._request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}"))
        head_commit_sha: str = ref_data["object"]["sha"]

        # 2. Get the tree SHA of the current HEAD commit.
        commit_data = cast(
            dict[str, Any], await self._request("GET", f"/repos/{owner}/{repo}/git/commits/{head_commit_sha}")
        )
        base_tree_sha: str = commit_data["tree"]["sha"]

        # 3. Create a blob for each file.
        tree_entries: list[dict[str, str]] = []
        for file in files:
            path = file["path"]
            content = file["content"]
            blob_body = {
                "content": base64.b64encode(content.encode()).decode(),
                "encoding": "base64",
            }
            blob_data = cast(
                dict[str, Any], await self._request("POST", f"/repos/{owner}/{repo}/git/blobs", body=blob_body)
            )
            tree_entries.append(
                {
                    "path": path,
                    "mode": "100644",  # regular file
                    "type": "blob",
                    "sha": blob_data["sha"],
                }
            )

        # 4. Create a new tree on top of the base tree (or from scratch if authoritative).
        tree_body: dict[str, Any] = {
            "tree": tree_entries,
        }
        if not authoritative:
            tree_body["base_tree"] = base_tree_sha

        tree_data = cast(
            dict[str, Any], await self._request("POST", f"/repos/{owner}/{repo}/git/trees", body=tree_body)
        )
        new_tree_sha: str = tree_data["sha"]

        # 5. Create a commit.
        commit_body: dict[str, Any] = {
            "message": commit_message,
            "tree": new_tree_sha,
            "parents": [head_commit_sha],
        }
        new_commit = cast(
            dict[str, Any], await self._request("POST", f"/repos/{owner}/{repo}/git/commits", body=commit_body)
        )
        new_commit_sha: str = new_commit["sha"]

        # 6. Update the branch ref to point to the new commit.
        await self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
            body={"sha": new_commit_sha},
        )

        logger.info(
            "Pushed %d files to %s/%s@%s, commit=%s",
            len(files),
            owner,
            repo,
            branch,
            new_commit_sha,
        )
        return new_commit_sha

    # ------------------------------------------------------------------
    # Pull requests
    # ------------------------------------------------------------------

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        head: str | None = None,
        state: str = "open",
    ) -> list[PrInfo]:
        """Return open PRs, optionally filtered by *head* branch.

        *head* should be in the form ``owner:branch``.
        """
        params: dict[str, str] = {"state": state, "per_page": "100"}
        if head:
            params["head"] = head
        data = cast(list[dict[str, Any]], await self._request("GET", f"/repos/{owner}/{repo}/pulls", params=params))
        return [_pr_from_json(item) for item in data]

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        *,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> PrInfo:
        """Open a pull request and return its info."""
        pr_body: dict[str, Any] = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }
        data = cast(dict[str, Any], await self._request("POST", f"/repos/{owner}/{repo}/pulls", body=pr_body))
        return _pr_from_json(data)

    # ------------------------------------------------------------------
    # Check runs
    # ------------------------------------------------------------------

    async def get_check_runs(self, owner: str, repo: str, ref: str) -> list[CheckRun]:
        """Return all check runs for *ref* (commit SHA or branch name)."""
        ref_escaped = quote(ref, safe="")
        data = cast(
            dict[str, Any],
            await self._request(
                "GET",
                f"/repos/{owner}/{repo}/commits/{ref_escaped}/check-runs",
                params={"per_page": "100"},
            ),
        )
        return [_check_run_from_json(item) for item in data.get("check_runs", [])]

    async def poll_checks(
        self,
        owner: str,
        repo: str,
        ref: str,
        *,
        timeout: float = _CHECK_POLL_TIMEOUT,
        interval: float = _CHECK_POLL_INTERVAL,
    ) -> list[CheckRun]:
        """Poll until all check runs for *ref* complete or *timeout* is exceeded.

        Returns the final list of check runs.
        Raises ``GitHubChecksTimedOutError`` on timeout.
        """
        deadline = time.monotonic() + timeout
        while True:
            runs = await self.get_check_runs(owner, repo, ref)
            if runs and all(r.status == "completed" for r in runs):
                logger.info(
                    "All %d check runs completed for ref=%s on %s/%s",
                    len(runs),
                    ref,
                    owner,
                    repo,
                )
                return runs

            if not runs:
                # No checks registered yet; treat as passed (no required checks).
                logger.info(
                    "No check runs found for ref=%s on %s/%s — treating as passed",
                    ref,
                    owner,
                    repo,
                )
                return []

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                pending = [r.name for r in runs if r.status != "completed"]
                raise GitHubChecksTimedOutError(
                    f"Check runs timed out after {timeout:.0f}s; still pending: {pending}",
                )

            wait = min(interval, remaining)
            logger.info(
                "Check runs not yet complete for ref=%s (%d/%d done). Waiting %.0f s …",
                ref,
                sum(1 for r in runs if r.status == "completed"),
                len(runs),
                wait,
            )
            await asyncio.sleep(wait)

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    async def merge_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        *,
        method: str = "squash",
    ) -> MergeResult:
        """Merge *pr_number* using *method* (merge | squash | rebase)."""
        body: dict[str, Any] = {"merge_method": method}
        data = cast(
            dict[str, Any], await self._request("PUT", f"/repos/{owner}/{repo}/pulls/{pr_number}/merge", body=body)
        )
        return MergeResult(
            sha=data.get("sha", ""),
            merged=bool(data.get("merged", False)),
            message=data.get("message", ""),
        )


# ---------------------------------------------------------------------------
# JSON deserialisers
# ---------------------------------------------------------------------------


def _repo_from_json(data: dict[str, Any]) -> RepoInfo:
    return RepoInfo(
        name=data["name"],
        full_name=data["full_name"],
        html_url=data["html_url"],
        clone_url=data["clone_url"],
        private=bool(data.get("private", True)),
        default_branch=data.get("default_branch", "main"),
    )


def _pr_from_json(data: dict[str, Any]) -> PrInfo:
    merged = bool(data.get("merged", False) or data.get("merged_at"))
    return PrInfo(
        number=int(data["number"]),
        html_url=data["html_url"],
        state=data.get("state", "open"),
        head_sha=data["head"]["sha"],
        title=data.get("title", ""),
        merged=merged,
        merge_commit_sha=data.get("merge_commit_sha"),
    )


def _check_run_from_json(data: dict[str, Any]) -> CheckRun:
    return CheckRun(
        id=int(data["id"]),
        name=data.get("name", ""),
        status=data.get("status", ""),
        conclusion=data.get("conclusion"),
        html_url=data.get("html_url", ""),
    )


def _parse_owner_repo(github_url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub HTTPS URL."""
    pattern = r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$"
    match = re.match(pattern, github_url.strip())
    if match is None:
        raise GitHubError(f"Cannot parse owner/repo from github_repo_url: {github_url!r}")
    return match.group(1), match.group(2)


def _is_rate_limit_response(resp: httpx.Response) -> bool:
    """Detect both primary (429) and GitHub-style 403 rate-limit responses."""
    if resp.status_code == 429:
        return True
    if resp.status_code != 403:
        return False
    if resp.headers.get("X-RateLimit-Remaining", "").strip() == "0":
        return True
    message = _response_message(resp).lower()
    return "rate limit" in message


def _compute_retry_after_seconds(resp: httpx.Response, attempt: int) -> float:
    """Compute retry delay honoring Retry-After while still growing exponentially."""
    raw_retry_after = resp.headers.get("Retry-After")
    retry_after: float | None = None
    if raw_retry_after:
        try:
            retry_after = float(raw_retry_after)
        except ValueError:
            retry_after = None

    exponential_backoff = _BASE_BACKOFF * (2**attempt)
    if retry_after is None:
        return float(exponential_backoff)
    return float(max(retry_after, exponential_backoff))


def _response_message(resp: httpx.Response) -> str:
    """Return a best-effort human-readable message from a GitHub response."""
    try:
        payload = resp.json()
    except ValueError:
        return resp.text
    if isinstance(payload, dict):
        return str(payload.get("message", resp.text))
    return resp.text
