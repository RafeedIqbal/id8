from __future__ import annotations

import pytest

from app.config import Settings
from app.github.auth import resolve_github_auth


def make_settings(**overrides: str) -> Settings:
    defaults = {
        "github_token": "",
        "github_app_id": "",
        "github_app_private_key": "",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def test_resolve_github_auth_prefers_pat() -> None:
    config = make_settings(
        github_token="ghp_pat_token",
        github_app_id="123456",
        github_app_private_key="-----BEGIN PRIVATE KEY-----...",
    )

    auth = resolve_github_auth(config)

    assert auth.mode == "token"
    assert auth.token == "ghp_pat_token"
    assert auth.app_id is None
    assert auth.app_private_key is None


def test_resolve_github_auth_falls_back_to_app_credentials() -> None:
    config = make_settings(
        github_app_id="123456",
        github_app_private_key="-----BEGIN PRIVATE KEY-----...",
    )

    auth = resolve_github_auth(config)

    assert auth.mode == "app"
    assert auth.app_id == "123456"
    assert auth.app_private_key == "-----BEGIN PRIVATE KEY-----..."
    assert auth.token is None


def test_resolve_github_auth_returns_none_without_credentials() -> None:
    auth = resolve_github_auth(make_settings())

    assert auth.mode == "none"
    assert auth.token is None
    assert auth.app_id is None
    assert auth.app_private_key is None


def test_resolve_github_auth_requires_both_app_fields() -> None:
    with pytest.raises(ValueError, match="Incomplete GitHub App credentials"):
        resolve_github_auth(make_settings(github_app_id="123456"))

    with pytest.raises(ValueError, match="Incomplete GitHub App credentials"):
        resolve_github_auth(make_settings(github_app_private_key="-----BEGIN PRIVATE KEY-----..."))

