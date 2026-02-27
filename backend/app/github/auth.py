from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config import Settings, settings

GitHubAuthMode = Literal["none", "token", "app"]


@dataclass(frozen=True, slots=True)
class GitHubAuth:
    mode: GitHubAuthMode
    token: str | None = None
    app_id: str | None = None
    app_private_key: str | None = None


def resolve_github_auth(config: Settings = settings) -> GitHubAuth:
    token = config.github_token.strip()
    app_id = config.github_app_id.strip()
    app_private_key = config.github_app_private_key.strip()

    if token:
        # PAT mode is the preferred path for this MVP.
        return GitHubAuth(mode="token", token=token)

    if app_id and app_private_key:
        return GitHubAuth(mode="app", app_id=app_id, app_private_key=app_private_key)

    if app_id or app_private_key:
        raise ValueError(
            "Incomplete GitHub App credentials. Set both GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY.",
        )

    return GitHubAuth(mode="none")
