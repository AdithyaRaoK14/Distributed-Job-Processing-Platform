from __future__ import annotations
from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


# ── Job schemas ───────────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    type: str = Field(..., examples=["process_image", "send_email"])
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: str = Field(default="medium", pattern="^(high|medium|low)$")
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=120, ge=5, le=3600)
    delay_seconds: Optional[float] = Field(default=None, ge=0)
    run_at: Optional[datetime] = Field(default=None, description="Run at exact UTC time")
    idempotency_key: Optional[str] = Field(
        default=None,
        max_length=256,
        description=(
            "Optional client-generated deduplication key. "
            "If a job with this key already exists, the existing job is returned "
            "instead of creating a new one. Prevents duplicate submissions on "
            "network retries. Does NOT prevent a single job from executing more "
            "than once if the worker crashes mid-execution."
        ),
    )


class JobResponse(BaseModel):
    id: str
    type: str
    payload: dict[str, Any]
    priority: str
    status: str
    retry_count: int
    max_retries: int
    timeout_seconds: int
    error: Optional[str]
    result: Optional[dict[str, Any]]
    worker_id: Optional[str]
    idempotency_key: Optional[str]
    scheduled_at: Optional[datetime]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int
    page: int
    page_size: int


# ── Worker schemas ────────────────────────────────────────────────────────────

class WorkerResponse(BaseModel):
    id: str
    hostname: Optional[str]
    status: str
    concurrency: int
    active_jobs: int
    last_heartbeat: Optional[datetime]
    registered_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Metric schemas ────────────────────────────────────────────────────────────

class QueueDepth(BaseModel):
    pending: int
    processing: int
    scheduled: int
    high_priority: int
    medium_priority: int
    low_priority: int


class MetricsResponse(BaseModel):
    queue_depth: QueueDepth
    total_completed: int
    total_failed: int
    total_dead_lettered: int
    active_workers: int
    dead_workers: int
    jobs_per_second: float


# ── Retry schema ──────────────────────────────────────────────────────────────

class RetryJobResponse(BaseModel):
    job_id: str
    message: str
