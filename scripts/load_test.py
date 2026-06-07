#!/usr/bin/env python3
"""
Load test for the job queue.

Usage:
    python scripts/load_test.py --jobs 500 --concurrency 50 --type noop
    python scripts/load_test.py --jobs 200 --type process_image --priority high

Measures:
  - Submission throughput (jobs/sec submitted)
  - End-to-end completion rate (jobs completed within timeout)
  - P50/P95/P99 completion latency
"""

import argparse
import asyncio
import time
import statistics
from datetime import datetime

import httpx


BASE_URL = "http://localhost:8000"
PAYLOADS = {
    "noop":           {},
    "process_image":  {"url": "https://example.com/test.jpg", "operations": ["resize"]},
    "send_email":     {"to": "load@test.com", "subject": "Load Test"},
    "generate_report":{"type": "summary", "rows": 100},
    "data_pipeline":  {"source": "test_db", "records": 50},
    "flaky_job":      {},
    "failing_job":    {"reason": "load test"},
}


async def submit_job(client: httpx.AsyncClient, job_type: str, priority: str) -> dict | None:
    try:
        resp = await client.post("/api/jobs/submit", json={
            "type": job_type,
            "payload": PAYLOADS.get(job_type, {}),
            "priority": priority,
            "max_retries": 2,
            "timeout_seconds": 60,
        })
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [WARN] Submit failed: {e}")
        return None


async def wait_for_completion(
    client: httpx.AsyncClient, job_ids: list[str], timeout_sec: float = 120
) -> dict[str, dict]:
    """Poll until all jobs finish or timeout."""
    completed = {}
    deadline = time.time() + timeout_sec
    remaining = set(job_ids)

    while remaining and time.time() < deadline:
        batch = list(remaining)[:50]  # check 50 at a time
        tasks = [client.get(f"/api/jobs/{jid}") for jid in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for jid, res in zip(batch, results):
            if isinstance(res, Exception):
                continue
            job = res.json()
            if job["status"] in ("completed", "failed", "dead_lettered"):
                completed[jid] = job
                remaining.discard(jid)

        if remaining:
            await asyncio.sleep(0.5)

    return completed


async def run_load_test(
    n_jobs: int,
    concurrency: int,
    job_type: str,
    priority: str,
    wait: bool,
):
    print(f"\n{'='*60}")
    print(f"  Distributed Job Queue — Load Test")
    print(f"{'='*60}")
    print(f"  Jobs       : {n_jobs}")
    print(f"  Concurrency: {concurrency}")
    print(f"  Type       : {job_type}")
    print(f"  Priority   : {priority}")
    print(f"  Wait done  : {wait}")
    print(f"{'='*60}\n")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        # ── Submission phase ───────────────────────────────────────────────────
        semaphore = asyncio.Semaphore(concurrency)

        async def guarded_submit(job_type, priority):
            async with semaphore:
                return await submit_job(client, job_type, priority)

        print(f"Submitting {n_jobs} jobs…")
        t0 = time.time()
        tasks = [guarded_submit(job_type, priority) for _ in range(n_jobs)]
        results = await asyncio.gather(*tasks)
        elapsed_submit = time.time() - t0

        submitted = [r for r in results if r is not None]
        n_submitted = len(submitted)
        submit_rps = n_submitted / elapsed_submit

        print(f"  Submitted  : {n_submitted}/{n_jobs}")
        print(f"  Time       : {elapsed_submit:.2f}s")
        print(f"  Throughput : {submit_rps:.1f} jobs/sec\n")

        if not wait or not submitted:
            _print_summary(n_submitted, n_jobs, submit_rps, [], elapsed_submit)
            return

        # ── Completion phase ───────────────────────────────────────────────────
        job_ids = [r["id"] for r in submitted]
        print(f"Waiting for {n_submitted} jobs to complete (timeout=120s)…")

        t1 = time.time()
        completed = await wait_for_completion(client, job_ids, timeout_sec=120)
        elapsed_wait = time.time() - t1

        n_completed  = sum(1 for j in completed.values() if j["status"] == "completed")
        n_failed     = sum(1 for j in completed.values() if j["status"] == "failed")
        n_dlq        = sum(1 for j in completed.values() if j["status"] == "dead_lettered")
        n_timeout    = n_submitted - len(completed)

        # Latency (created_at → completed_at)
        latencies = []
        for job in completed.values():
            if job.get("created_at") and job.get("completed_at"):
                c = datetime.fromisoformat(job["created_at"].replace("Z", "+00:00"))
                d = datetime.fromisoformat(job["completed_at"].replace("Z", "+00:00"))
                latencies.append((d - c).total_seconds())

        _print_summary(n_submitted, n_jobs, submit_rps, latencies, elapsed_submit,
                       n_completed, n_failed, n_dlq, n_timeout, elapsed_wait)

        # Fetch final metrics
        try:
            m = (await client.get("/api/metrics")).json()
            w = (await client.get("/api/workers")).json()
            print(f"\n  Active workers   : {m.get('active_workers', '?')}")
            print(f"  Queue depth now  : {m['queue_depth']['pending']} pending")
            print(f"  Jobs/sec (live)  : {m.get('jobs_per_second', '?')}")
            print(f"  Worker count     : {len(w)}")
        except Exception:
            pass


def _print_summary(
    n_submitted, n_jobs, submit_rps, latencies,
    elapsed_submit, n_completed=None, n_failed=None,
    n_dlq=None, n_timeout=None, elapsed_wait=None,
):
    print(f"\n{'─'*60}")
    print(f"  RESULTS")
    print(f"{'─'*60}")
    print(f"  Jobs submitted   : {n_submitted}/{n_jobs}")
    print(f"  Submit rate      : {submit_rps:.1f} jobs/sec")
    print(f"  Submit time      : {elapsed_submit:.2f}s")

    if n_completed is not None:
        print(f"\n  Completed        : {n_completed}")
        print(f"  Failed           : {n_failed}")
        print(f"  Dead-lettered    : {n_dlq}")
        print(f"  Timed out (poll) : {n_timeout}")
        print(f"  Wait time        : {elapsed_wait:.2f}s")

    if latencies:
        latencies.sort()
        print(f"\n  Latency (end-to-end):")
        print(f"    P50  : {statistics.median(latencies):.2f}s")
        print(f"    P95  : {latencies[int(len(latencies)*0.95)]:.2f}s")
        print(f"    P99  : {latencies[int(len(latencies)*0.99)]:.2f}s")
        print(f"    Max  : {max(latencies):.2f}s")

    print(f"{'─'*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Queue Load Test")
    parser.add_argument("--jobs",        type=int,  default=100,    help="Total jobs to submit")
    parser.add_argument("--concurrency", type=int,  default=20,     help="Concurrent submissions")
    parser.add_argument("--type",        type=str,  default="noop", help="Job type")
    parser.add_argument("--priority",    type=str,  default="medium", choices=["high","medium","low"])
    parser.add_argument("--wait",        action="store_true",        help="Wait for job completion")
    args = parser.parse_args()

    asyncio.run(run_load_test(
        n_jobs=args.jobs,
        concurrency=args.concurrency,
        job_type=args.type,
        priority=args.priority,
        wait=args.wait,
    ))
