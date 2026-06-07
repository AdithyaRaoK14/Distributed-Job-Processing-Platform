"""
Test configuration.

Key design decisions:
  - SQLite (aiosqlite) for the database — no Postgres needed in unit tests.
  - fakeredis for Redis — the FastAPI lifespan is patched so it uses fakeredis
    instead of trying to connect to a real Redis server.
  - run_orchestrator is patched to a no-op so it doesn't spin an infinite loop.
  - After lifespan startup completes, app.state.queue is replaced with mock_queue
    so individual test assertions (enqueue.assert_awaited_once) work cleanly.
"""

import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from unittest.mock import AsyncMock, MagicMock, patch

TEST_DB_URL = "sqlite+aiosqlite:///./test_jobqueue.db"


# ── Event loop (session-scoped) ───────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Database (session-scoped — create tables once, reuse across tests) ─────────

@pytest_asyncio.fixture(scope="session")
async def db_engine():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from backend.app.database import Base
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Mock queue ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def mock_queue():
    queue = MagicMock()
    queue.enqueue      = AsyncMock()
    queue.pop          = AsyncMock(return_value=None)
    queue.mark_processing = AsyncMock()
    queue.mark_done    = AsyncMock()
    queue.mark_failed  = AsyncMock()
    queue.remove_from_processing = AsyncMock()
    queue.requeue      = AsyncMock()
    queue.get_depths   = AsyncMock(return_value={
        "pending": 0, "processing": 0, "scheduled": 0,
        "high_priority": 0, "medium_priority": 0, "low_priority": 0,
    })
    queue.get_stats    = AsyncMock(return_value={"submitted": 0, "completed": 0, "failed": 0})
    queue.redis        = AsyncMock()
    return queue


# ── HTTP test client ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(mock_queue, db_engine):
    """
    Full FastAPI test client with:
      - SQLite instead of Postgres
      - fakeredis instead of real Redis (lifespan succeeds without any running server)
      - orchestrator stubbed out (no infinite background loop)
      - app.state.queue replaced with mock_queue after lifespan startup
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    try:
        import fakeredis.aioredis as fakeredis
    except ImportError:
        pytest.skip("fakeredis not installed — run: pip install fakeredis")

    import redis.asyncio as real_aioredis
    from backend.app.main import app as fastapi_app
    from backend.app.database import get_db

    # Override DB dependency to use SQLite
    test_session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with test_session() as s:
            yield s

    fastapi_app.dependency_overrides[get_db] = override_get_db

    # Stub out the orchestrator — it's an infinite loop we don't want in tests
    async def noop_orchestrator(*args, **kwargs):
        return

    # Patch Redis so the lifespan's `aioredis.from_url(...)` call returns fakeredis.
    # This lets the lifespan complete cleanly without a real Redis server.
    fake_redis = fakeredis.FakeRedis(decode_responses=True)

    with patch.object(real_aioredis, "from_url", return_value=fake_redis), \
         patch("backend.app.main.run_orchestrator", side_effect=noop_orchestrator):

        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as ac:
            # Lifespan startup has now completed.
            # Replace the real RedisQueue (backed by fakeredis) with our mock
            # so individual tests can assert on enqueue.assert_awaited_once() etc.
            fastapi_app.state.queue = mock_queue
            yield ac

    fastapi_app.dependency_overrides.clear()


# ── Direct DB session (for fixtures that insert rows directly) ─────────────────

@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
