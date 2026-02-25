"""Ephemeral in-memory Stitch auth cache keyed by run ID.

Used to avoid persisting raw Stitch credentials in artifact content.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from .base import StitchAuthContext

_AUTH_TTL = timedelta(hours=1)
_cache: dict[uuid.UUID, tuple[StitchAuthContext, datetime]] = {}


def cache_stitch_auth(run_id: uuid.UUID, auth: StitchAuthContext) -> None:
    """Store auth for a run with a short TTL."""
    _purge_expired()
    _cache[run_id] = (auth, datetime.now(tz=UTC))


def get_cached_stitch_auth(run_id: uuid.UUID) -> StitchAuthContext | None:
    """Load cached auth for a run, if present and not expired."""
    _purge_expired()
    entry = _cache.get(run_id)
    if entry is None:
        return None
    return entry[0]


def clear_cached_stitch_auth(run_id: uuid.UUID) -> None:
    """Delete cached auth for a run."""
    _cache.pop(run_id, None)


def _purge_expired() -> None:
    now = datetime.now(tz=UTC)
    expired_ids = [
        run_id
        for run_id, (_, cached_at) in _cache.items()
        if now - cached_at > _AUTH_TTL
    ]
    for run_id in expired_ids:
        _cache.pop(run_id, None)
