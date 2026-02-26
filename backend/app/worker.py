"""ID8 worker — polls for pending runs and retry jobs.

Run as a standalone process via ``python -m app.worker``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.project_run import ProjectRun
from app.models.retry_job import RetryJob
from app.orchestrator.engine import run_orchestrator
from app.orchestrator.nodes import NODE_REGISTRY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("id8.worker")

POLL_INTERVAL_SECONDS = 2


async def _process_pending_runs(db: AsyncSession) -> int:
    """Find runs whose current_node is actionable (not wait, not terminal) and drive them."""
    wait_or_terminal_nodes = [
        n.value
        for n, meta in NODE_REGISTRY.items()
        if meta.is_wait_node or meta.is_terminal
    ]

    result = await db.execute(
        select(ProjectRun).where(
            ProjectRun.current_node.notin_(wait_or_terminal_nodes),
        )
    )
    runs = result.scalars().all()

    for run in runs:
        logger.info("Processing pending run=%s at node=%s", run.id, run.current_node)
        try:
            await run_orchestrator(run.id, db)
            await db.commit()
        except Exception:
            logger.exception("Error processing run=%s", run.id)
            await db.rollback()

    return len(runs)


async def _process_retry_jobs(db: AsyncSession) -> int:
    """Find due retry jobs and re-enter the orchestrator for each."""
    now = datetime.now(tz=UTC)
    result = await db.execute(
        select(RetryJob).where(
            RetryJob.scheduled_for <= now,
            RetryJob.processed_at.is_(None),
        )
    )
    jobs = result.scalars().all()

    for job in jobs:
        logger.info("Processing retry job=%s for run=%s node=%s", job.id, job.run_id, job.node_name)
        try:
            await run_orchestrator(job.run_id, db)
            job.processed_at = now
            await db.commit()
        except Exception:
            logger.exception("Error processing retry job=%s", job.id)
            await db.rollback()

    return len(jobs)


async def main() -> None:
    logger.info("ID8 worker started — polling every %ds", POLL_INTERVAL_SECONDS)
    while True:
        try:
            async with async_session() as db:
                runs_processed = await _process_pending_runs(db)
                retries_processed = await _process_retry_jobs(db)

                if runs_processed or retries_processed:
                    logger.info("Cycle complete: runs=%d retries=%d", runs_processed, retries_processed)
        except Exception:
            logger.exception("Worker poll cycle failed")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
