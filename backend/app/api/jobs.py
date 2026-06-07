import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Job
from ..schemas import JobCreate, JobResponse, JobListResponse, RetryJobResponse
from ..queue.redis_queue import RedisQueue

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


# ── Submit ─────────────────────────────────────────────────────────────────────

@router.post("/submit", response_model=JobResponse, status_code=201)
async def submit_job(body: JobCreate, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """
    Submit a new job.

    Idempotency: if `idempotency_key` is provided and a job with that key already
    exists, the existing job is returned with HTTP 200 (not 201). This makes it safe
    to retry a submission after a network failure without risking duplicate execution.

    Note: idempotency_key deduplicates at the *submission* layer only. It does not
    guarantee exactly-once *execution*. This system provides at-least-once delivery.
    """
    queue: RedisQueue = request.app.state.queue

    # ── Idempotency check (fast path before any write) ─────────────────────────
    if body.idempotency_key:
        existing = await db.execute(
            select(Job).where(Job.idempotency_key == body.idempotency_key)
        )
        existing_job = existing.scalar_one_or_none()
        if existing_job:
            logger.info(f"Idempotency hit for key={body.idempotency_key!r}, returning job {existing_job.id}")
            response.status_code = 200
            return existing_job

    # ── Resolve scheduled time ─────────────────────────────────────────────────
    run_at: Optional[float] = None
    scheduled_dt: Optional[datetime] = None

    if body.run_at:
        run_at = body.run_at.timestamp()
        scheduled_dt = body.run_at
    elif body.delay_seconds and body.delay_seconds > 0:
        run_at = datetime.now(timezone.utc).timestamp() + body.delay_seconds
        scheduled_dt = datetime.fromtimestamp(run_at, tz=timezone.utc)

    job = Job(
        id=uuid.uuid4().hex,
        type=body.type,
        payload=body.payload,
        priority=body.priority,
        max_retries=body.max_retries,
        timeout_seconds=body.timeout_seconds,
        status="pending",
        retry_count=0,
        scheduled_at=scheduled_dt,
        idempotency_key=body.idempotency_key,
    )
    db.add(job)

    try:
        await db.commit()
    except IntegrityError:
        # Race condition: another request inserted the same idempotency_key
        # between our check and our insert. Fetch and return the winner.
        await db.rollback()
        existing = await db.execute(
            select(Job).where(Job.idempotency_key == body.idempotency_key)
        )
        existing_job = existing.scalar_one_or_none()
        if existing_job:
            logger.info(f"Idempotency race resolved for key={body.idempotency_key!r}")
            response.status_code = 200
            return existing_job
        # Integrity error for an unrelated reason — re-raise
        raise HTTPException(status_code=409, detail="Job could not be created due to a conflict")

    await db.refresh(job)
    await queue.enqueue(job.id, job.priority, run_at)
    return job


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("", response_model=JobListResponse)
async def list_jobs(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    job_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    q = select(Job)
    if status:
        q = q.where(Job.status == status)
    if priority:
        q = q.where(Job.priority == priority)
    if job_type:
        q = q.where(Job.type == job_type)

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one()

    q = q.order_by(Job.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    jobs = result.scalars().all()
    return {"jobs": jobs, "total": total, "page": page, "page_size": page_size}


# ── Dead-letter list (before /{job_id} to avoid route conflict) ────────────────

@router.get("/dead-letter/list", response_model=JobListResponse)
async def list_dead_letter(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    q = select(Job).where(Job.status == "dead_lettered")
    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one()

    q = q.order_by(Job.completed_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    jobs = result.scalars().all()
    return {"jobs": jobs, "total": total, "page": page, "page_size": page_size}


# ── Get single ─────────────────────────────────────────────────────────────────

@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Retry dead-lettered ────────────────────────────────────────────────────────

@router.post("/{job_id}/retry", response_model=RetryJobResponse)
async def retry_dead_letter(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Re-enqueue a dead-lettered job, resetting its retry counter.
    The idempotency_key is cleared so the job can be submitted again if needed.
    """
    queue: RedisQueue = request.app.state.queue

    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "dead_lettered":
        raise HTTPException(status_code=400, detail=f"Job is not dead-lettered (status={job.status})")

    job.status = "pending"
    job.retry_count = 0
    job.error = None
    job.result = None
    job.worker_id = None
    job.started_at = None
    job.completed_at = None
    job.idempotency_key = None  # clear so a new submission with same key can be made
    await db.commit()

    await queue.enqueue(job.id, job.priority)
    return {"job_id": job.id, "message": "Job re-enqueued successfully"}


# ── Delete ─────────────────────────────────────────────────────────────────────

@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await db.delete(job)
    await db.commit()
