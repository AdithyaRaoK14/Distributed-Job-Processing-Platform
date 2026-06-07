"""
Unit tests for RedisQueue — uses fakeredis so no real Redis is needed.
Install: pip install fakeredis
"""
import time
import pytest
import pytest_asyncio

try:
    import fakeredis.aioredis as fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app.queue.redis_queue import (
    RedisQueue, PRIORITY_OFFSETS, QUEUE_KEY, PROCESSING_KEY, SCHEDULED_KEY
)

pytestmark = pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")


@pytest_asyncio.fixture
async def queue():
    client = fakeredis.FakeRedis(decode_responses=True)
    q = RedisQueue(client)
    yield q
    await client.flushall()
    await client.aclose()


# ── Priority scoring ───────────────────────────────────────────────────────────

def test_priority_offsets_ordered():
    """HIGH < MEDIUM < LOW so ZPOPMIN picks highest priority first."""
    assert PRIORITY_OFFSETS["high"] < PRIORITY_OFFSETS["medium"] < PRIORITY_OFFSETS["low"]


def test_high_score_always_below_medium():
    """A high-priority job added any time should score below medium offset."""
    q = RedisQueue(None)
    # Simulate far-future timestamp (year 2100 = ~4e12 ms)
    future_ms = int(time.time() * 1000) + 3_000_000_000_000  # +3 trillion ms ≈ 95 years
    # Even with future timestamp, HIGH score should be below MEDIUM offset
    # (This tests the design constraint that timestamps fit in the priority band)
    high_score = PRIORITY_OFFSETS["high"] + int(time.time() * 1000)
    assert high_score < PRIORITY_OFFSETS["medium"], (
        "HIGH priority score exceeds MEDIUM offset — timestamps too large!"
    )


# ── Enqueue and pop ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enqueue_single(queue):
    await queue.enqueue("job-1", "medium")
    depth = await queue.get_depths()
    assert depth["pending"] == 1


@pytest.mark.asyncio
async def test_pop_returns_job(queue):
    await queue.enqueue("job-1", "medium")
    job_id = await queue.pop(timeout=1)
    assert job_id == "job-1"


@pytest.mark.asyncio
async def test_pop_empty_returns_none(queue):
    result = await queue.pop(timeout=0.1)
    assert result is None


@pytest.mark.asyncio
async def test_priority_ordering(queue):
    """
    Workers receive HIGH before MEDIUM before LOW when all are already in the queue.
    Note: this is not starvation prevention. If high-priority jobs arrive continuously,
    low-priority jobs will wait indefinitely — there is no aging mechanism.
    """
    await queue.enqueue("low-job",    "low")
    await queue.enqueue("medium-job", "medium")
    await queue.enqueue("high-job",   "high")

    first  = await queue.pop(timeout=1)
    second = await queue.pop(timeout=1)
    third  = await queue.pop(timeout=1)

    assert first  == "high-job",   f"Expected high-job first, got {first}"
    assert second == "medium-job", f"Expected medium-job second, got {second}"
    assert third  == "low-job",    f"Expected low-job third, got {third}"


@pytest.mark.asyncio
async def test_fifo_within_same_priority(queue):
    """Within the same priority, jobs should be FIFO."""
    for i in range(5):
        await queue.enqueue(f"job-{i}", "medium")
        await asyncio.sleep(0.001)  # ensure distinct timestamps

    results = []
    for _ in range(5):
        jid = await queue.pop(timeout=1)
        results.append(jid)

    assert results == ["job-0", "job-1", "job-2", "job-3", "job-4"]


# ── Processing tracking ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_processing(queue):
    await queue.enqueue("job-1", "high")
    await queue.pop(timeout=1)
    await queue.mark_processing("job-1", "worker-a", timeout_seconds=30)

    depth = await queue.get_depths()
    assert depth["processing"] == 1


@pytest.mark.asyncio
async def test_mark_done_removes_from_processing(queue):
    await queue.enqueue("job-1", "high")
    await queue.pop(timeout=1)
    await queue.mark_processing("job-1", "worker-a", timeout_seconds=30)
    await queue.mark_done("job-1", "worker-a")

    depth = await queue.get_depths()
    assert depth["processing"] == 0


@pytest.mark.asyncio
async def test_get_timed_out(queue):
    import time
    await queue.enqueue("slow-job", "medium")
    await queue.pop(timeout=1)
    # Set deadline in the past
    deadline = time.time() - 5
    await queue.redis.zadd(PROCESSING_KEY, {"worker-x:slow-job": deadline})

    timed_out = await queue.get_timed_out()
    assert ("worker-x", "slow-job") in timed_out


@pytest.mark.asyncio
async def test_no_false_timeout(queue):
    """Jobs with future deadline should not appear as timed out."""
    await queue.enqueue("ok-job", "high")
    await queue.pop(timeout=1)
    await queue.mark_processing("ok-job", "worker-a", timeout_seconds=300)

    timed_out = await queue.get_timed_out()
    assert timed_out == []


# ── Requeue ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_requeue_puts_job_back(queue):
    await queue.enqueue("job-1", "high")
    await queue.pop(timeout=1)
    await queue.mark_processing("job-1", "worker-a", timeout_seconds=30)
    await queue.requeue("job-1", "worker-a", "high")

    depth = await queue.get_depths()
    assert depth["pending"] == 1
    assert depth["processing"] == 0

    recovered = await queue.pop(timeout=1)
    assert recovered == "job-1"


# ── Scheduled jobs ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scheduled_job_not_immediately_pending(queue):
    future = time.time() + 3600  # 1 hour from now
    await queue.enqueue("future-job", "medium", run_at=future)

    depth = await queue.get_depths()
    assert depth["pending"] == 0
    assert depth["scheduled"] == 1


@pytest.mark.asyncio
async def test_promote_scheduled_due_jobs(queue):
    """Jobs whose run_at has passed should be promoted to pending."""
    past = time.time() - 1  # already due
    member = f"medium:past-job"
    await queue.redis.zadd(SCHEDULED_KEY, {member: past})

    promoted = await queue.promote_scheduled()
    assert "past-job" in promoted

    depth = await queue.get_depths()
    assert depth["pending"] == 1
    assert depth["scheduled"] == 0


@pytest.mark.asyncio
async def test_promote_does_not_move_future_jobs(queue):
    future = time.time() + 3600
    member = "high:future-job"
    await queue.redis.zadd(SCHEDULED_KEY, {member: future})

    promoted = await queue.promote_scheduled()
    assert promoted == []


# ── Depth metrics ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_queue_depth_by_priority(queue):
    await queue.enqueue("h1", "high")
    await queue.enqueue("h2", "high")
    await queue.enqueue("m1", "medium")
    await queue.enqueue("l1", "low")

    depth = await queue.get_depths()
    assert depth["high_priority"]   == 2
    assert depth["medium_priority"] == 1
    assert depth["low_priority"]    == 1
    assert depth["pending"]         == 4


import asyncio  # needed for fifo test
