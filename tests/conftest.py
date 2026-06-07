import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from unittest.mock import AsyncMock, MagicMock

# Use in-memory SQLite for tests
TEST_DB_URL = "sqlite+aiosqlite:///./test.db"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    from backend.app.database import Base
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def mock_queue():
    queue = MagicMock()
    queue.enqueue = AsyncMock()
    queue.pop = AsyncMock(return_value=None)
    queue.mark_processing = AsyncMock()
    queue.mark_done = AsyncMock()
    queue.mark_failed = AsyncMock()
    queue.get_depths = AsyncMock(return_value={
        "pending": 0, "processing": 0, "scheduled": 0,
        "high_priority": 0, "medium_priority": 0, "low_priority": 0,
    })
    queue.get_stats = AsyncMock(return_value={"submitted": 0, "completed": 0, "failed": 0})
    return queue


@pytest_asyncio.fixture
async def app(mock_queue, db_engine):
    """FastAPI test app with mocked Redis queue and SQLite DB."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from backend.app.main import app as fastapi_app
    from backend.app import database as db_module
    from backend.app.database import Base

    # Override DB
    test_engine = db_engine
    test_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with test_session() as s:
            yield s

    from backend.app.database import get_db
    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.state.queue = mock_queue

    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
