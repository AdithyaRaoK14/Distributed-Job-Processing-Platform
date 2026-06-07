from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import WorkerNode
from ..schemas import WorkerResponse

router = APIRouter(prefix="/api/workers", tags=["workers"])


@router.get("", response_model=list[WorkerResponse])
async def list_workers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkerNode).order_by(WorkerNode.registered_at.desc()))
    return result.scalars().all()


@router.post("/heartbeat")
async def worker_heartbeat(request: Request, db: AsyncSession = Depends(get_db)):
    """Called by worker processes to register/refresh themselves."""
    body = await request.json()
    worker_id = body["worker_id"]
    hostname = body.get("hostname", worker_id)
    concurrency = body.get("concurrency", 5)
    active_jobs = body.get("active_jobs", 0)

    result = await db.execute(select(WorkerNode).where(WorkerNode.id == worker_id))
    worker = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if worker is None:
        worker = WorkerNode(
            id=worker_id,
            hostname=hostname,
            concurrency=concurrency,
            active_jobs=active_jobs,
            last_heartbeat=now,
        )
        db.add(worker)
    else:
        worker.status = "active"
        worker.active_jobs = active_jobs
        worker.last_heartbeat = now
        worker.hostname = hostname

    await db.commit()
    return {"ok": True}


@router.get("/{worker_id}", response_model=WorkerResponse)
async def get_worker(worker_id: str, db: AsyncSession = Depends(get_db)):
    from fastapi import HTTPException
    result = await db.execute(select(WorkerNode).where(WorkerNode.id == worker_id))
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    return worker
