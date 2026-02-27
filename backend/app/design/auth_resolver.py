from __future__ import annotations

import os

from app.config import settings

from .base import StitchAuthContext, StitchAuthMethod


def get_default_stitch_auth() -> StitchAuthContext | None:
    """Return Stitch credentials from environment configuration, if present."""
    api_key = settings.stitch_mcp_api_key.strip()
    if api_key:
        return StitchAuthContext(
            auth_method=StitchAuthMethod.API_KEY,
            api_key=api_key,
        )

    oauth_token = (
        settings.stitch_mcp_oauth_token or settings.stitch_access_token or os.getenv("STITCH_ACCESS_TOKEN", "")
    ).strip()
    goog_user_project = (
        settings.stitch_mcp_goog_user_project or settings.google_cloud_project or os.getenv("GOOGLE_CLOUD_PROJECT", "")
    ).strip()
    if oauth_token and goog_user_project:
        return StitchAuthContext(
            auth_method=StitchAuthMethod.OAUTH,
            oauth_token=oauth_token,
            goog_user_project=goog_user_project,
        )

    return None


def stitch_auth_configured() -> bool:
    return get_default_stitch_auth() is not None
