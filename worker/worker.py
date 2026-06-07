"""
Worker process.

Each worker:
  - Registers itself with the backend via HTTP heartbeat.
  - Polls the Redis priority queue for jobs (BZPOPMIN).
  - Processes up to `concurrency` jobs simultaneously (asyncio.Semaphore).
  - Sends heartbeats every 5 seconds.
  - Handles retry with exponential backoff and dead-lettering.
  - Enforces per-job timeouts (asyncio.wait_for).
  - Marks in-flight jobs in the processing sorted set for orchestrator recovery.
"""

import asyncio
import json
import logging
import os
import signal
import socket
import time
import uuid
#from datetime import datetime, timezone

import asyncpg
import httpx
import redis.asyncio as aioredis

try:
    from .job_handlers import JOB_HANDLERS
except ImportError:
    from job_handlers import JOB_HANDLERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
)
logger = logging.getLogger("worker")

# ── Config ─────────────────────────────────────────────────────────────────────
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/jobqueue")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "5"))
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "5"))
DEFAULT_TIMEOUT = int(os.environ.get("JOB_TIMEOUT", "120"))

# Queue keys — must match backend/app/queue/redis_queue.py
QUEUE_KEY = "jq:pending"
PROCESSING_KEY = "jq:processing"
THROUGHPUT_KEY = "jq:throughput"

PRIORITY_OFFSETS = {
    "high": 0,
    "medium": 2_000_000_000_000,
    "low": 4_000_000_000_000,
}


def pending_score(priority: str) -> int:
    offset = PRIORITY_OFFSETS.get(priority, PRIORITY_OFFSETS["medium"])
    return offset + int(time.time() * 1_000)


class Worker:
    def __init__(self):
        self.worker_id = f"worker-{uuid.uuid4().hex[:10]}"
        self.hostname = socket.gethostname()
        self.concurrency = CONCURRENCY
        self.running = True
        self.active_jobs: dict[str, float] = {}   # job_id → started_at
        self.redis: aioredis.Redis | None = None
        self.db: asyncpg.Pool | None = None
        self.http: httpx.AsyncClient | None = None
        self.semaphore = asyncio.Semaphore(CONCURRENCY)

    # ── Connect ────────────────────────────────────────────────────────────────

    async def connect(self):
        self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
        self.db = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        self.http = httpx.AsyncClient(base_url=BACKEND_URL, timeout=5.0)
        logger.info(f"Worker {self.worker_id} connected (concurrency={self.concurrency})")

    async def disconnect(self):
        if self.http:
            await self.http.aclose()
        if self.redis:
            await self.redis.aclose()
        if self.db:
            await self.db.close()

    # ── Register / Heartbeat ───────────────────────────────────────────────────

    async def heartbeat_loop(self):
        while self.running:
            try:
                await self.http.post("/api/workers/heartbeat", json={
                    "worker_id": self.worker_id,
                    "hostname": self.hostname,
                    "concurrency": self.concurrency,
                    "active_jobs": len(self.active_jobs),
                })
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    # ── Main processing loop ───────────────────────────────────────────────────

    async def process_loop(self):
        tasks: set[asyncio.Task] = set()

        while self.running:
            # Only pull when we have capacity
            if self.semaphore._value > 0:
                try:
                    result = await self.redis.bzpopmin(QUEUE_KEY, timeout=1)
                except Exception as e:
                    logger.error(f"Redis pop error: {e}")
                    await asyncio.sleep(1)
                    continue

                if result:
                    _key, job_id, _score = result
                    task = asyncio.create_task(self._run_job(job_id))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
            else:
                # At capacity — wait briefly for a slot
                await asyncio.sleep(0.05)

            # Clean up finished tasks
            tasks = {t for t in tasks if not t.done()}

        # Wait for in-flight jobs to finish
        if tasks:
            logger.info(f"Waiting for {len(tasks)} in-flight jobs to finish…")
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── Job execution ──────────────────────────────────────────────────────────

    async def _run_job(self, job_id: str):
        async with self.semaphore:
            self.active_jobs[job_id] = time.time()
            try:
                await self._execute(job_id)
            except Exception as e:
                logger.error(f"Unhandled error in job {job_id}: {e}", exc_info=True)
            finally:
                self.active_jobs.pop(job_id, None)
                # Always remove from processing set
                await self.redis.zrem(PROCESSING_KEY, f"{self.worker_id}:{job_id}")

    async def _execute(self, job_id: str):
        # Fetch job from DB
        async with self.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)

        if row is None:
            logger.error(f"Job {job_id} not found in DB — skipping")
            return

        job = dict(row)
        timeout = job.get("timeout_seconds") or DEFAULT_TIMEOUT
        priority = job.get("priority", "medium")
        retry_count = job.get("retry_count", 0)
        max_retries = job.get("max_retries", 3)

        # Mark in processing set so orchestrator can recover on crash
        deadline = time.time() + timeout
        await self.redis.zadd(PROCESSING_KEY, {f"{self.worker_id}:{job_id}": deadline})

        # Mark running in DB
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE jobs SET status='running', started_at=NOW(), worker_id=$1, updated_at=NOW() WHERE id=$2",
                self.worker_id, job_id,
            )

        handler = JOB_HANDLERS.get(job["type"])
        if handler is None:
            await self._fail(job_id, f"No handler for type '{job['type']}'", retry_count, max_retries, priority)
            return

        try:
            payload = job.get("payload") or {}
            if isinstance(payload, str):
                payload = json.loads(payload)

            logger.info(f"[{self.worker_id}] Starting job {job_id} type={job['type']} timeout={timeout}s")
            result = await asyncio.wait_for(handler(payload), timeout=timeout)
            await self._complete(job_id, result)

            # Record throughput
            await self.redis.hincrby(THROUGHPUT_KEY, str(int(time.time())), 1)
            await self.redis.expire(THROUGHPUT_KEY, 30)

        except asyncio.TimeoutError:
            logger.warning(f"Job {job_id} timed out after {timeout}s")
            await self._fail(job_id, f"Timed out after {timeout}s", retry_count, max_retries, priority)
        except Exception as e:
            logger.warning(f"Job {job_id} failed: {e}")
            await self._fail(job_id, str(e), retry_count, max_retries, priority)

    async def _complete(self, job_id: str, result: dict):
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE jobs SET status='completed', result=$1, completed_at=NOW(), updated_at=NOW() WHERE id=$2",
                json.dumps(result), job_id,
            )
        logger.info(f"[{self.worker_id}] ✓ Job {job_id} completed")

    async def _fail(self, job_id: str, error: str, retry_count: int, max_retries: int, priority: str):
        if retry_count < max_retries:
            # Exponential backoff: 1s, 2s, 4s, 8s…
            delay = float(2 ** retry_count)
            new_count = retry_count + 1

            async with self.db.acquire() as conn:
                await conn.execute(
                    """UPDATE jobs
                       SET status='pending', retry_count=$1, error=$2, worker_id=NULL,
                           updated_at=NOW()
                       WHERE id=$3""",
                    new_count, error, job_id,
                )

            logger.warning(
                f"[{self.worker_id}] ✗ Job {job_id} failed "
                f"(attempt {new_count}/{max_retries}), retrying in {delay}s: {error}"
            )
            # Wait for backoff, then re-enqueue
            await asyncio.sleep(delay)
            score = pending_score(priority)
            await self.redis.zadd(QUEUE_KEY, {job_id: score})
        else:
            async with self.db.acquire() as conn:
                await conn.execute(
                    """UPDATE jobs
                       SET status='dead_lettered', error=$1, completed_at=NOW(), updated_at=NOW()
                       WHERE id=$2""",
                    error, job_id,
                )
            logger.error(
                f"[{self.worker_id}] ☠ Job {job_id} dead-lettered after {max_retries} retries: {error}"
            )

    # ── Run ────────────────────────────────────────────────────────────────────

    async def run(self):
        await self.connect()
        try:
            await asyncio.gather(
                self.heartbeat_loop(),
                self.process_loop(),
            )
        finally:
            await self.disconnect()


# ── Entry point ────────────────────────────────────────────────────────────────

async def main():
    worker = Worker()

    loop = asyncio.get_running_loop()

    def _shutdown(*_):
        logger.info("Shutdown signal received")
        worker.running = False

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
