"""
Orchestrator runs as a FastAPI background task.

Responsibilities:
  1. Promote scheduled jobs that are due into the pending queue.
  2. Detect worker heartbeat timeouts → mark workers dead, reassign their jobs.
  3. Detect job processing timeouts → requeue or dead-letter stale processing entries.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update


from .config import settings
from .database import async_session
from .models import Job, WorkerNode
from .queue.redis_queue import RedisQueue

logger = logging.getLogger(__name__)


async def _promote_scheduled(queue: RedisQueue) -> None:
    promoted = await queue.promote_scheduled()
    if promoted:
        # Update DB status for promoted jobs
        async with async_session() as db:
            await db.execute(
                update(Job).where(Job.id.in_(promoted)).values(scheduled_at=None)
            )
            await db.commit()
        logger.info(f"Promoted {len(promoted)} scheduled jobs")


async def _check_worker_heartbeats(queue: RedisQueue) -> None:
    """Mark workers dead if their heartbeat has lapsed; reassign their in-flight jobs."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.heartbeat_timeout)

    async with async_session() as db:
        # Find active workers with stale heartbeats
        result = await db.execute(
            select(WorkerNode).where(
                WorkerNode.status == "active",
                WorkerNode.last_heartbeat < cutoff,
            )
        )
        dead_workers = result.scalars().all()

        for worker in dead_workers:
            logger.warning(f"Worker {worker.id} heartbeat lapsed — marking dead")
            worker.status = "dead"

            # Find jobs that were running on this worker
            jobs_result = await db.execute(
                select(Job).where(Job.worker_id == worker.id, Job.status == "running")
            )
            orphaned_jobs = jobs_result.scalars().all()

            for job in orphaned_jobs:
                logger.warning(f"Requeuing orphaned job {job.id} from dead worker {worker.id}")
                # Remove from processing set (best-effort)
                await queue.remove_from_processing(job.id, worker.id)
                # Reset job to pending so it gets requeued
                job.status = "pending"
                job.worker_id = None
                job.started_at = None
                # Re-enqueue immediately
                await queue.enqueue(job.id, job.priority)

        await db.commit()


async def _check_job_timeouts(queue: RedisQueue) -> None:
    """
    Handle processing-set entries whose deadline has passed.
    The worker should have killed the job itself, but this is a backstop.
    """
    timed_out = await queue.get_timed_out()
    if not timed_out:
        return

    async with async_session() as db:
        for worker_id, job_id in timed_out:
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job is None:
                # Stale entry — just remove it
                await queue.remove_from_processing(job_id, worker_id)
                continue

            if job.status != "running":
                # Already resolved by the worker
                await queue.remove_from_processing(job_id, worker_id)
                continue

            logger.warning(f"Job {job_id} timed out in processing set; retry_count={job.retry_count}")
            await queue.remove_from_processing(job_id, worker_id)

            if job.retry_count < job.max_retries:
                delay = 2 ** job.retry_count
                job.retry_count += 1
                job.status = "pending"
                job.worker_id = None
                job.error = "Timeout — requeued by orchestrator"
                await queue.requeue(job_id, worker_id, job.priority, delay=delay)
            else:
                job.status = "dead_lettered"
                job.completed_at = datetime.now(timezone.utc)
                job.error = "Exceeded max retries after timeout"
                await queue.mark_failed()

        await db.commit()


async def run_orchestrator(queue: RedisQueue) -> None:
    """Main orchestrator loop — runs forever as a background asyncio task."""
    logger.info("Orchestrator started")
    while True:
        try:
            await _promote_scheduled(queue)
            await _check_worker_heartbeats(queue)
            await _check_job_timeouts(queue)
        except Exception as exc:
            logger.error(f"Orchestrator error: {exc}", exc_info=True)
        await asyncio.sleep(settings.orchestrator_interval)
