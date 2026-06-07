"""
Job handlers: async functions that receive a payload dict and return a result dict.
Register a new handler by adding it to JOB_HANDLERS.
"""

import asyncio
import random
import logging

logger = logging.getLogger(__name__)


async def handle_process_image(payload: dict) -> dict:
    """Simulate image processing pipeline."""
    image_url = payload.get("url", "unknown")
    operations = payload.get("operations", ["resize", "compress"])
    duration = random.uniform(0.5, 3.0)
    await asyncio.sleep(duration)
    return {
        "image_url": image_url,
        "operations_applied": operations,
        "output_size_kb": random.randint(50, 500),
        "duration_ms": int(duration * 1000),
    }


async def handle_send_email(payload: dict) -> dict:
    """Simulate sending an email via SMTP."""
    recipient = payload.get("to", "user@example.com")
    subject = payload.get("subject", "(no subject)")
    await asyncio.sleep(random.uniform(0.1, 0.8))
    message_id = f"msg-{random.randint(100000, 999999)}@mail.example.com"
    logger.info(f"Email sent to {recipient}: {subject} → {message_id}")
    return {"message_id": message_id, "recipient": recipient, "status": "delivered"}


async def handle_generate_report(payload: dict) -> dict:
    """Simulate generating a data report."""
    report_type = payload.get("type", "summary")
    rows = payload.get("rows", 1000)
    duration = rows / 10_000 * random.uniform(1.0, 3.0)
    await asyncio.sleep(duration)
    return {
        "report_type": report_type,
        "rows_processed": rows,
        "output_url": f"s3://reports/{report_type}-{random.randint(1000, 9999)}.csv",
        "duration_ms": int(duration * 1000),
    }


async def handle_data_pipeline(payload: dict) -> dict:
    """Simulate an ETL data pipeline."""
    source = payload.get("source", "database")
    records = payload.get("records", 500)
    duration = records / 1000 * random.uniform(0.5, 2.0)
    await asyncio.sleep(duration)
    return {
        "source": source,
        "records_extracted": records,
        "records_transformed": records,
        "records_loaded": int(records * 0.99),
        "duration_ms": int(duration * 1000),
    }


async def handle_thumbnail(payload: dict) -> dict:
    """Generate image thumbnails at multiple sizes."""
    source = payload.get("source_url", "image.jpg")
    sizes = payload.get("sizes", [128, 256, 512])
    await asyncio.sleep(random.uniform(0.2, 1.5))
    return {
        "source": source,
        "thumbnails": [{"size": s, "url": f"cdn.example.com/thumb/{s}/{source}"} for s in sizes],
    }


async def handle_slow_job(payload: dict) -> dict:
    """Intentionally slow job — useful for demonstrating timeouts."""
    sleep_for = payload.get("seconds", 60)
    await asyncio.sleep(sleep_for)
    return {"slept_for": sleep_for}


async def handle_failing_job(payload: dict) -> dict:
    """Intentionally fails — demonstrates retry and dead-letter queue."""
    raise RuntimeError(f"Intentional failure: {payload.get('reason', 'test error')}")


async def handle_flaky_job(payload: dict) -> dict:
    """Fails 70% of the time — good for showing retry behaviour."""
    if random.random() < 0.7:
        raise RuntimeError("Flaky job failed (try again!)")
    return {"message": "Lucky run — succeeded!"}


async def handle_noop(payload: dict) -> dict:
    """Instant no-op — useful for throughput benchmarking."""
    return {"noop": True}


JOB_HANDLERS = {
    "process_image": handle_process_image,
    "send_email": handle_send_email,
    "generate_report": handle_generate_report,
    "data_pipeline": handle_data_pipeline,
    "thumbnail": handle_thumbnail,
    "slow_job": handle_slow_job,
    "failing_job": handle_failing_job,
    "flaky_job": handle_flaky_job,
    "noop": handle_noop,
}
