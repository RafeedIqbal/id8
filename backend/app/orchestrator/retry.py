"""Retry logic for the ID8 orchestrator.

Provides exponential backoff scheduling, retry-job creation, and the
``RetryableError`` / ``RateLimitError`` exception hierarchy.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.retry_job import RetryJob

logger = logging.getLogger("id8.orchestrator.retry")

MAX_RETRIES: int = 3
BASE_DELAY_SECONDS: float = 3.0  # 3^1 = 3s, 3^2 = 9s, 3^3 = 27s


class RetryableError(Exception):
    """Raised when a node handler encounters a transient, retryable failure."""


class RateLimitError(RetryableError):
    """Raised when a model provider returns a rate-limit response.

    Signals the engine to switch to the fallback model profile before retrying.
    """

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def compute_backoff(attempt: int) -> float:
    """Return seconds to wait before retry *attempt* (1-indexed).

    Uses exponential backoff ``3^attempt`` with ±20 % jitter.
    """
    base = BASE_DELAY_SECONDS**attempt  # 3, 9, 27
    jitter = base * 0.2 * (random.random() * 2 - 1)  # ±20 % # noqa: S311
    return max(0.1, base + jitter)


async def schedule_retry(
    *,
    run_id: uuid.UUID,
    node_name: str,
    retry_attempt: int,
    error_message: str,
    use_fallback_profile: bool,
    minimum_delay_seconds: float | None = None,
    db: AsyncSession,
) -> RetryJob | None:
    """Create a ``RetryJob`` if the node has retries remaining.

    Returns the created ``RetryJob``, or ``None`` if retries are exhausted.
    """
    if retry_attempt > MAX_RETRIES:
        logger.warning(
            "Retry exhausted for run=%s node=%s after %d retries",
            run_id,
            node_name,
            retry_attempt - 1,
        )
        return None

    delay = compute_backoff(retry_attempt)
    if minimum_delay_seconds is not None:
        delay = max(delay, minimum_delay_seconds)
    scheduled_for = datetime.now(tz=UTC) + timedelta(seconds=delay)
    payload: dict[str, str | float] = {"error": error_message}
    payload["delay_seconds"] = round(delay, 4)
    if use_fallback_profile:
        payload["model_profile"] = "fallback"
    if minimum_delay_seconds is not None:
        payload["retry_after_seconds"] = minimum_delay_seconds

    job = RetryJob(
        run_id=run_id,
        node_name=node_name,
        retry_attempt=retry_attempt,
        scheduled_for=scheduled_for,
        payload=payload,
    )
    db.add(job)
    await db.flush()

    logger.info(
        "Scheduled retry for run=%s node=%s attempt=%d at %s",
        run_id,
        node_name,
        retry_attempt,
        scheduled_for.isoformat(),
    )
    return job
