"""Background worker: claim jobs, run them, scheduler tick."""

from __future__ import annotations

import asyncio
import time
import uuid

from minuta import ingest, jobs
from minuta.db import close_pool, open_pool
from minuta.index import index_version
from minuta.settings import get_settings

WORKER_ID = f"worker-{uuid.uuid4().hex[:8]}"


async def _run_job(job: dict) -> None:
    kind, payload = job["kind"], job.get("payload") or {}
    try:
        if kind == "transcript.fetch":
            result = await ingest.process_video(payload["video_id"])
        elif kind == "transcript.index":
            result = await index_version(payload["version_id"])
        elif kind == "channel.sync":
            result = await ingest.sync_channel(payload["channel_id"])
        else:
            await jobs.fail(job["id"], f"unknown job kind {kind}", retryable=False)
            return
        status = (result or {}).get("status")
        if status in ("deferred", "blocked_auth"):
            await jobs.complete(job["id"], result)
        else:
            await jobs.complete(job["id"], result)
    except Exception as exc:  # noqa: BLE001 - jobs must never kill the loop
        await jobs.fail(job["id"], f"{type(exc).__name__}: {exc}", retryable=True)


async def drain(max_seconds: int = 240, concurrency: int | None = None) -> dict:
    settings = get_settings()
    concurrency = concurrency or settings.worker_concurrency
    started, running = 0, set()
    begin = time.monotonic()
    while time.monotonic() - begin < max_seconds:
        running = {t for t in running if not t.done()}
        for _ in range(concurrency - len(running)):
            claimed = await jobs.claim(WORKER_ID, limit=1)
            if not claimed:
                break
            started += 1
            running.add(asyncio.create_task(_run_job(claimed[0])))
        if not running:
            if not await jobs.claim(WORKER_ID, limit=1):
                break
            await asyncio.sleep(settings.worker_poll_seconds)
            continue
        done, _ = await asyncio.wait(running, timeout=settings.worker_poll_seconds)
        running -= done
    if running:
        await asyncio.gather(*running, return_exceptions=True)
    return {"jobs_started": started}


async def run_tick(max_seconds: int = 240) -> dict:
    from minuta.db import fetch_all

    await open_pool()
    try:
        pending = await fetch_all(
            "select id from channels where discovery_status != 'complete' limit 5")
        for ch in pending:
            await jobs.enqueue("channel.sync", {"channel_id": str(ch["id"])}, priority=40)
        return {"scheduler": {"channels_queued": len(pending)}, **await drain(max_seconds)}
    finally:
        await close_pool()
