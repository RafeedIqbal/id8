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

MAX_ATTEMPTS: int = 3
BASE_DELAY_SECONDS: float = 3.0  # 3^1 = 3s, 3^2 = 9s, 3^3 = 27s


class RetryableError(Exception):
    """Raised when a node handler encounters a transient, retryable failure."""


class RateLimitError(RetryableError):
    """Raised when a model provider returns a rate-limit response.

    Signals the engine to switch to the fallback model profile before retrying.
    """


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
    attempt: int,
    error_message: str,
    db: AsyncSession,
) -> RetryJob | None:
    """Create a ``RetryJob`` if the node has retries remaining.

    Returns the created ``RetryJob``, or ``None`` if retries are exhausted.
    """
    if attempt >= MAX_ATTEMPTS:
        logger.warning(
            "Retry exhausted for run=%s node=%s after %d attempts",
            run_id,
            node_name,
            attempt,
        )
        return None

    delay = compute_backoff(attempt + 1)
    scheduled_for = datetime.now(tz=UTC) + timedelta(seconds=delay)

    job = RetryJob(
        run_id=run_id,
        node_name=node_name,
        retry_attempt=attempt + 1,
        scheduled_for=scheduled_for,
        payload={"error": error_message},
    )
    db.add(job)
    await db.flush()

    logger.info(
        "Scheduled retry for run=%s node=%s attempt=%d at %s",
        run_id,
        node_name,
        attempt + 1,
        scheduled_for.isoformat(),
    )
    return job
