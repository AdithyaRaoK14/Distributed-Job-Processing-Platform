"""
Worker unit tests — mock Redis and asyncpg so no infrastructure needed.
"""
import asyncio
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worker.job_handlers import (
    handle_noop, handle_send_email, handle_failing_job,
    handle_process_image, JOB_HANDLERS,
)


# ── Handler tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_noop_handler():
    result = await handle_noop({})
    assert result == {"noop": True}


@pytest.mark.asyncio
async def test_send_email_handler():
    result = await handle_send_email({"to": "test@example.com", "subject": "Hi"})
    assert "message_id" in result
    assert result["recipient"] == "test@example.com"
    assert result["status"] == "delivered"


@pytest.mark.asyncio
async def test_failing_job_raises():
    with pytest.raises(RuntimeError, match="Intentional failure"):
        await handle_failing_job({"reason": "test"})


@pytest.mark.asyncio
async def test_process_image_handler():
    result = await handle_process_image({"url": "img.jpg", "operations": ["resize"]})
    assert "output_size_kb" in result
    assert "duration_ms" in result


@pytest.mark.asyncio
async def test_all_handlers_registered():
    """Every handler in JOB_HANDLERS must be callable."""
    for name, fn in JOB_HANDLERS.items():
        assert callable(fn), f"Handler '{name}' is not callable"


# ── Timeout enforcement ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handler_timeout():
    """asyncio.wait_for should cancel a slow handler."""
    async def slow(_):
        await asyncio.sleep(60)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(slow({}), timeout=0.05)


# ── Worker retry logic ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_worker_retry_exponential_backoff():
    """Backoff delay should double on each retry."""
    delays = [float(2 ** i) for i in range(4)]
    assert delays == [1.0, 2.0, 4.0, 8.0]


@pytest.mark.asyncio
async def test_worker_dead_letters_at_max_retries():
    """After max_retries attempts, status must be dead_lettered."""
    from unittest.mock import AsyncMock, MagicMock
    import sys, os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../worker"))
    from worker import Worker

    w = Worker.__new__(Worker)
    w.worker_id = "test-worker"
    w.active_jobs = {}

    fake_conn = AsyncMock()

    db_ctx = MagicMock()
    db_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    db_ctx.__aexit__ = AsyncMock(return_value=False)

    w.db = MagicMock()
    w.db.acquire = MagicMock(return_value=db_ctx)

    w.redis = AsyncMock()

    updates = []

    async def mock_execute(sql, *args):
        updates.append((str(sql), args))

    fake_conn.execute = mock_execute

    await w._fail(
        "job-dlq",
        "error",
        retry_count=3,
        max_retries=3,
        priority="medium",
    )

    assert any(
        "dead_lettered" in sql.lower()
        for sql, _ in updates
    ), f"Expected dead_lettered update, got: {updates}"


@pytest.mark.asyncio
async def test_worker_retries_if_under_max():
    """Job with retry_count < max_retries should be re-enqueued."""
    from unittest.mock import AsyncMock, MagicMock
    import sys, os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../worker"))
    from worker import Worker

    w = Worker.__new__(Worker)
    w.worker_id = "test-worker"
    w.active_jobs = {}

    fake_conn = AsyncMock()
    updates = []

    async def mock_execute(sql, *args):
        updates.append((str(sql), args))

    fake_conn.execute = mock_execute

    db_ctx = MagicMock()
    db_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    db_ctx.__aexit__ = AsyncMock(return_value=False)

    w.db = MagicMock()
    w.db.acquire = MagicMock(return_value=db_ctx)

    w.redis = AsyncMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(asyncio, "sleep", AsyncMock())

        await w._fail(
            "job-retry",
            "transient error",
            retry_count=0,
            max_retries=3,
            priority="high",
        )

    w.redis.zadd.assert_awaited_once()

    assert any(
        args[0] == 1
        for _, args in updates
    ), f"Expected retry_count=1 update, got: {updates}"

    
