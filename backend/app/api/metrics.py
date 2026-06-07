from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Job, WorkerNode
from ..schemas import MetricsResponse, QueueDepth
from ..queue.redis_queue import RedisQueue

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
async def get_metrics(request: Request, db: AsyncSession = Depends(get_db)):
    queue: RedisQueue = request.app.state.queue

    # Queue depths from Redis
    depths = await queue.get_depths()
    #redis_stats = await queue.get_stats()

    # DB aggregates
    status_counts_result = await db.execute(
        select(Job.status, func.count(Job.id)).group_by(Job.status)
    )
    status_map = dict(status_counts_result.all())

    worker_counts_result = await db.execute(
        select(WorkerNode.status, func.count(WorkerNode.id)).group_by(WorkerNode.status)
    )
    worker_map = dict(worker_counts_result.all())

    # Simple throughput: completed / uptime is hard without a start time;
    # use Redis completed counter vs DB count as a rate proxy.
    completed = status_map.get("completed", 0)
    failed = status_map.get("failed", 0)
    dead_lettered = status_map.get("dead_lettered", 0)

    # Jobs per second approximation via last 60s window stored in Redis
    jps = await _jobs_per_second(queue)

    return MetricsResponse(
        queue_depth=QueueDepth(**depths),
        total_completed=completed,
        total_failed=failed,
        total_dead_lettered=dead_lettered,
        active_workers=worker_map.get("active", 0),
        dead_workers=worker_map.get("dead", 0),
        jobs_per_second=jps,
    )


async def _jobs_per_second(queue: RedisQueue) -> float:
    """Estimate throughput using a sliding 10-second window in Redis."""
    import time
    redis = queue.redis
    now = int(time.time())
    window = 10
    key = "jq:throughput"

    # Increment current-second bucket
    bucket = str(now)
    await redis.hincrby(key, bucket, 1)
    await redis.expire(key, window * 2)

    # Sum counts over the window
    all_buckets = await redis.hgetall(key)
    total = sum(
        int(v) for k, v in all_buckets.items()
        if now - int(k) <= window
    )
    return round(total / window, 2)
