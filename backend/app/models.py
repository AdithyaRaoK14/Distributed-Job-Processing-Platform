from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, UniqueConstraint
from sqlalchemy.sql import func
from .database import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # Database-level enforcement: two submissions with the same idempotency_key
        # cannot both exist. The unique constraint is partial (NULL keys are excluded
        # because NULL != NULL in SQL, so omitting the key opts out of deduplication).
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )

    id = Column(String(64), primary_key=True)
    type = Column(String(128), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    priority = Column(String(16), nullable=False, default="medium")   # high / medium / low
    status = Column(String(32), nullable=False, default="pending")    # pending / running / completed / failed / dead_lettered
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    timeout_seconds = Column(Integer, nullable=False, default=120)
    error = Column(Text)
    result = Column(JSON)
    worker_id = Column(String(64))
    idempotency_key = Column(String(256), nullable=True, unique=True)  # optional dedup key
    scheduled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))


class WorkerNode(Base):
    __tablename__ = "workers"

    id = Column(String(64), primary_key=True)
    hostname = Column(String(256))
    status = Column(String(16), nullable=False, default="active")  # active / dead
    concurrency = Column(Integer, nullable=False, default=5)
    active_jobs = Column(Integer, nullable=False, default=0)
    last_heartbeat = Column(DateTime(timezone=True))
    registered_at = Column(DateTime(timezone=True), server_default=func.now())
