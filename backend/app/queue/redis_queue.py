"""
Redis-backed priority queue.

Scoring scheme (ZPOPMIN → lowest score first):
  HIGH   → 0            + timestamp_ms   (scores: 0 .. ~2e12)
  MEDIUM → 2_000_000_000_000 + timestamp_ms   (scores: 2e12 .. ~4e12)
  LOW    → 4_000_000_000_000 + timestamp_ms   (scores: 4e12 .. ~6e12)

Timestamps in milliseconds fit well under 2e12 until year 2603.

Processing set: members are "worker_id:job_id", score = deadline timestamp (seconds).
Scheduled set:  members are "priority:job_id",  score = run_at timestamp (seconds).
"""

import time
from typing import Optional
import redis.asyncio as aioredis

QUEUE_KEY = "jq:pending"
PROCESSING_KEY = "jq:processing"
SCHEDULED_KEY = "jq:scheduled"
STATS_KEY = "jq:stats"

PRIORITY_OFFSETS: dict[str, int] = {
    "high": 0,
    "medium": 2_000_000_000_000,
    "low": 4_000_000_000_000,
}


class RedisQueue:
    def __init__(self, client: aioredis.Redis):
        self.redis = client

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _pending_score(self, priority: str) -> int:
        offset = PRIORITY_OFFSETS.get(priority, PRIORITY_OFFSETS["medium"])
        return offset + int(time.time() * 1_000)

    # ── Enqueue ────────────────────────────────────────────────────────────────

    async def enqueue(self, job_id: str, priority: str, run_at: Optional[float] = None) -> None:
        """Push job to pending queue or scheduled set."""
        if run_at and run_at > time.time():
            member = f"{priority}:{job_id}"
            await self.redis.zadd(SCHEDULED_KEY, {member: run_at})
        else:
            score = self._pending_score(priority)
            await self.redis.zadd(QUEUE_KEY, {job_id: score})
        await self.redis.incr(f"{STATS_KEY}:submitted")

    # ── Pop ────────────────────────────────────────────────────────────────────

    async def pop(self, timeout: float = 1.0) -> Optional[str]:
        """Blocking pop of the highest-priority pending job. Returns job_id or None."""
        result = await self.redis.bzpopmin(QUEUE_KEY, timeout=timeout)
        if result:
            _key, job_id, _score = result
            return job_id
        return None

    # ── Processing tracking (at-least-once delivery) ───────────────────────────

    async def mark_processing(self, job_id: str, worker_id: str, timeout_seconds: int) -> None:
        deadline = time.time() + timeout_seconds
        await self.redis.zadd(PROCESSING_KEY, {f"{worker_id}:{job_id}": deadline})

    async def mark_done(self, job_id: str, worker_id: str) -> None:
        await self.redis.zrem(PROCESSING_KEY, f"{worker_id}:{job_id}")
        await self.redis.incr(f"{STATS_KEY}:completed")

    async def mark_failed(self) -> None:
        await self.redis.incr(f"{STATS_KEY}:failed")

    async def get_timed_out(self) -> list[tuple[str, str]]:
        """Return [(worker_id, job_id)] for jobs past their processing deadline."""
        now = time.time()
        entries = await self.redis.zrangebyscore(PROCESSING_KEY, "-inf", now)
        result = []
        for entry in entries:
            parts = entry.split(":", 1)
            if len(parts) == 2:
                result.append((parts[0], parts[1]))
        return result

    async def remove_from_processing(self, job_id: str, worker_id: str) -> None:
        await self.redis.zrem(PROCESSING_KEY, f"{worker_id}:{job_id}")

    async def requeue(self, job_id: str, worker_id: str, priority: str, delay: float = 0) -> None:
        """Remove from processing and push back to appropriate queue."""
        await self.remove_from_processing(job_id, worker_id)
        run_at = time.time() + delay if delay > 0 else None
        await self.enqueue(job_id, priority, run_at)

    # ── Scheduler promotion ────────────────────────────────────────────────────

    async def promote_scheduled(self) -> list[str]:
        """Move due scheduled jobs into the pending queue. Returns promoted job IDs."""
        now = time.time()
        due = await self.redis.zrangebyscore(SCHEDULED_KEY, "-inf", now)
        if not due:
            return []

        pipe = self.redis.pipeline(transaction=True)
        for member in due:
            pipe.zrem(SCHEDULED_KEY, member)
        results = await pipe.execute()

        promoted = []
        for member, removed in zip(due, results):
            if removed:
                priority, job_id = member.split(":", 1)
                score = self._pending_score(priority)
                await self.redis.zadd(QUEUE_KEY, {job_id: score})
                promoted.append(job_id)
        return promoted

    # ── Metrics ────────────────────────────────────────────────────────────────

    async def get_depths(self) -> dict:
        pending = await self.redis.zcard(QUEUE_KEY)
        processing = await self.redis.zcard(PROCESSING_KEY)
        scheduled = await self.redis.zcard(SCHEDULED_KEY)

        high = await self.redis.zcount(QUEUE_KEY, 0, PRIORITY_OFFSETS["medium"] - 1)
        medium = await self.redis.zcount(
            QUEUE_KEY, PRIORITY_OFFSETS["medium"], PRIORITY_OFFSETS["low"] - 1
        )
        low = await self.redis.zcount(QUEUE_KEY, PRIORITY_OFFSETS["low"], "+inf")

        return {
            "pending": pending,
            "processing": processing,
            "scheduled": scheduled,
            "high_priority": high,
            "medium_priority": medium,
            "low_priority": low,
        }

    async def get_stats(self) -> dict:
        submitted = int(await self.redis.get(f"{STATS_KEY}:submitted") or 0)
        completed = int(await self.redis.get(f"{STATS_KEY}:completed") or 0)
        failed = int(await self.redis.get(f"{STATS_KEY}:failed") or 0)
        return {"submitted": submitted, "completed": completed, "failed": failed}
