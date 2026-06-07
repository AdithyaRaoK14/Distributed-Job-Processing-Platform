import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_submit_job_basic(client, mock_queue):
    resp = await client.post("/api/jobs/submit", json={
        "type": "noop",
        "payload": {},
        "priority": "medium",
        "max_retries": 3,
        "timeout_seconds": 30,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["type"] == "noop"
    assert data["priority"] == "medium"
    assert data["status"] == "pending"
    assert data["retry_count"] == 0
    mock_queue.enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_job_high_priority(client, mock_queue):
    resp = await client.post("/api/jobs/submit", json={
        "type": "send_email",
        "payload": {"to": "test@example.com"},
        "priority": "high",
        "max_retries": 5,
        "timeout_seconds": 60,
    })
    assert resp.status_code == 201
    assert resp.json()["priority"] == "high"


@pytest.mark.asyncio
async def test_submit_job_invalid_priority(client):
    resp = await client.post("/api/jobs/submit", json={
        "type": "noop",
        "payload": {},
        "priority": "ultra",   # invalid
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_submit_job_with_delay(client, mock_queue):
    resp = await client.post("/api/jobs/submit", json={
        "type": "noop",
        "payload": {},
        "priority": "low",
        "delay_seconds": 60,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["scheduled_at"] is not None
    # Should have been queued into scheduled set
    mock_queue.enqueue.assert_awaited_once()
    call_kwargs = mock_queue.enqueue.call_args
    assert call_kwargs.args[2] is not None   # run_at provided


@pytest.mark.asyncio
async def test_get_job(client):
    # First submit
    resp = await client.post("/api/jobs/submit", json={"type": "noop", "payload": {}})
    job_id = resp.json()["id"]

    resp2 = await client.get(f"/api/jobs/{job_id}")
    assert resp2.status_code == 200
    assert resp2.json()["id"] == job_id


@pytest.mark.asyncio
async def test_get_job_not_found(client):
    resp = await client.get("/api/jobs/doesnotexist123")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_jobs_empty(client):
    resp = await client.get("/api/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert "jobs" in body
    assert "total" in body


@pytest.mark.asyncio
async def test_list_jobs_filter_by_status(client):
    # Submit a few jobs
    for _ in range(3):
        await client.post("/api/jobs/submit", json={"type": "noop", "payload": {}})

    resp = await client.get("/api/jobs?status=pending")
    assert resp.status_code == 200
    body = resp.json()
    assert all(j["status"] == "pending" for j in body["jobs"])


@pytest.mark.asyncio
async def test_dead_letter_list(client):
    resp = await client.get("/api/jobs/dead-letter/list")
    assert resp.status_code == 200
    body = resp.json()
    assert "jobs" in body


@pytest.mark.asyncio
async def test_retry_non_dead_lettered_job(client):
    resp = await client.post("/api/jobs/submit", json={"type": "noop", "payload": {}})
    job_id = resp.json()["id"]

    # Job is pending, not dead-lettered → should fail
    resp2 = await client.post(f"/api/jobs/{job_id}/retry")
    assert resp2.status_code == 400


@pytest.mark.asyncio
async def test_retry_dead_lettered_job(client, mock_queue, db_session):
    from backend.app.models import Job
    import uuid

    # Manually insert a dead-lettered job
    job = Job(
        id=uuid.uuid4().hex,
        type="failing_job",
        payload={},
        priority="medium",
        status="dead_lettered",
        retry_count=3,
        max_retries=3,
        timeout_seconds=30,
        error="Intentional failure",
    )
    db_session.add(job)
    await db_session.commit()

    resp = await client.post(f"/api/jobs/{job.id}/retry")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job.id
    mock_queue.enqueue.assert_awaited()


@pytest.mark.asyncio
async def test_metrics_endpoint(client):
    resp = await client.get("/api/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "queue_depth" in body
    assert "total_completed" in body
    assert "active_workers" in body
    assert "jobs_per_second" in body


@pytest.mark.asyncio
async def test_list_workers(client):
    resp = await client.get("/api/workers")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_worker_heartbeat(client):
    resp = await client.post("/api/workers/heartbeat", json={
        "worker_id": "test-worker-001",
        "hostname": "test-host",
        "concurrency": 5,
        "active_jobs": 2,
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Worker should now appear in list
    workers = await client.get("/api/workers")
    ids = [w["id"] for w in workers.json()]
    assert "test-worker-001" in ids


@pytest.mark.asyncio
async def test_submit_batch(client, mock_queue):
    """Submit 20 jobs concurrently — all should succeed."""
    import asyncio
    tasks = [
        client.post("/api/jobs/submit", json={"type": "noop", "payload": {"i": i}})
        for i in range(20)
    ]
    results = await asyncio.gather(*tasks)
    assert all(r.status_code == 201 for r in results)
    assert mock_queue.enqueue.await_count >= 20


# ── Idempotency tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idempotency_key_returns_same_job(client, mock_queue):
    """Two submissions with the same idempotency_key should return the same job ID."""
    body = {
        "type": "noop",
        "payload": {},
        "idempotency_key": "test-idem-key-001",
    }
    resp1 = await client.post("/api/jobs/submit", json=body)
    resp2 = await client.post("/api/jobs/submit", json=body)

    assert resp1.status_code == 201
    assert resp2.status_code == 200   # second call returns existing job
    assert resp1.json()["id"] == resp2.json()["id"]
    # Queue enqueue should only have been called once (for the first submission)
    assert mock_queue.enqueue.await_count == 1


@pytest.mark.asyncio
async def test_idempotency_key_different_keys_create_separate_jobs(client, mock_queue):
    """Different idempotency keys must create separate jobs."""
    mock_queue.enqueue.reset_mock()
    resp1 = await client.post("/api/jobs/submit", json={
        "type": "noop", "payload": {}, "idempotency_key": "key-A"
    })
    resp2 = await client.post("/api/jobs/submit", json={
        "type": "noop", "payload": {}, "idempotency_key": "key-B"
    })

    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["id"] != resp2.json()["id"]
    assert mock_queue.enqueue.await_count == 2


@pytest.mark.asyncio
async def test_no_idempotency_key_always_creates_new_job(client, mock_queue):
    """Without an idempotency_key, identical payloads create separate jobs."""
    mock_queue.enqueue.reset_mock()
    body = {"type": "noop", "payload": {"x": 1}}
    resp1 = await client.post("/api/jobs/submit", json=body)
    resp2 = await client.post("/api/jobs/submit", json=body)

    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["id"] != resp2.json()["id"]


@pytest.mark.asyncio
async def test_idempotency_key_persisted_in_response(client, mock_queue):
    """The idempotency_key should be visible in the job response."""
    mock_queue.enqueue.reset_mock()
    resp = await client.post("/api/jobs/submit", json={
        "type": "noop",
        "payload": {},
        "idempotency_key": "visible-key-test",
    })
    assert resp.status_code == 201
    assert resp.json()["idempotency_key"] == "visible-key-test"


@pytest.mark.asyncio
async def test_idempotency_key_cleared_after_retry(client, mock_queue, db_session):
    """After retrying a dead-lettered job, its idempotency_key is cleared
    so a new submission with the same key can be made if needed."""
    from backend.app.models import Job
    import uuid

    idem_key = f"dlq-retry-key-{uuid.uuid4().hex[:8]}"
    job = Job(
        id=uuid.uuid4().hex,
        type="failing_job",
        payload={},
        priority="medium",
        status="dead_lettered",
        retry_count=3,
        max_retries=3,
        timeout_seconds=30,
        error="Intentional failure",
        idempotency_key=idem_key,
    )
    db_session.add(job)
    await db_session.commit()

    resp = await client.post(f"/api/jobs/{job.id}/retry")
    assert resp.status_code == 200

    # Fetch the job and confirm key was cleared
    job_resp = await client.get(f"/api/jobs/{job.id}")
    assert job_resp.json()["idempotency_key"] is None
