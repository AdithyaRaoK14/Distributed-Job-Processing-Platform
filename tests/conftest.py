import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from unittest.mock import AsyncMock, MagicMock

# In-memory SQLite for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    from backend.app.database import Base

    # IMPORTANT: import models so SQLAlchemy registers tables
    from backend.app.models import Job, WorkerNode

    engine = create_async_engine(TEST_DB_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

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

    queue.get_depths = AsyncMock(
        return_value={
            "pending": 0,
            "processing": 0,
            "scheduled": 0,
            "high_priority": 0,
            "medium_priority": 0,
            "low_priority": 0,
        }
    )

    queue.get_stats = AsyncMock(
        return_value={
            "submitted": 0,
            "completed": 0,
            "failed": 0,
        }
    )

    return queue


@pytest_asyncio.fixture
async def app(mock_queue, db_engine):
    import sys
    import os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from backend.app.main import app as fastapi_app
    from backend.app.database import get_db

    test_session = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db():
        async with test_session() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.state.queue = mock_queue

    yield fastapi_app

    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
