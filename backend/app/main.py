import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .queue.redis_queue import RedisQueue
from .orchestrator import run_orchestrator
from .api import jobs as jobs_router
from .api import workers as workers_router
from .api import metrics as metrics_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────────
    logger.info("Initialising database…")
    await init_db()

    logger.info("Connecting to Redis…")
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    queue = RedisQueue(redis_client)
    app.state.queue = queue
    app.state.redis = redis_client

    logger.info("Starting orchestrator…")
    orchestrator_task = asyncio.create_task(run_orchestrator(queue))

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    orchestrator_task.cancel()
    try:
        await orchestrator_task
    except asyncio.CancelledError:
        pass
    await redis_client.aclose()
    logger.info("Backend shutdown complete")


app = FastAPI(
    title="Distributed Job Queue",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router.router)
app.include_router(workers_router.router)
app.include_router(metrics_router.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Empty init files
