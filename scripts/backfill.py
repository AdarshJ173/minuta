#!/usr/bin/env python3
"""Transcript backfill. Sequential by default; parallel with --concurrency.

Usage: PYTHONPATH=src python scripts/backfill.py [--max 200] [--sleep 15]
       [--concurrency 1]
Safe to stop and re-run at any time. Paid/turbo runs typically use
--concurrency 8 --sleep 0 (see docs/TURBO.md).
"""
from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, "src")

from minuta import ingest
from minuta.db import close_pool, fetch_all, open_pool
from minuta.index import index_version


async def _one(video: dict, sem: asyncio.Semaphore, stats: dict, tag: str) -> None:
    async with sem:
        try:
            res = await ingest.process_video(str(video["id"]))
        except Exception as exc:  # noqa: BLE001 - counted, loop continues
            stats["failed"] = stats.get("failed", 0) + 1
            print(f"[{tag}] {video['youtube_video_id']} FAILED {type(exc).__name__}", flush=True)
            return
        status = res.get("status", "?")
        stats[status] = stats.get(status, 0) + 1
        print(f"[{tag}] {video['youtube_video_id']} {status}", flush=True)
        if status == "stored":
            idx = await index_version(res["version_id"])
            print(f"[{tag}]   indexed chunks={idx.get('chunks')}", flush=True)


async def main() -> int:
    args = _parse_args()
    await open_pool()
    stats: dict[str, int] = {}
    try:
        videos = await fetch_all(
            """select id, youtube_video_id from videos
               where transcript_status != 'stored' and excluded = false
               order by published_at nulls last, youtube_video_id limit %s""",
            (args.max,),
        )
        print(f"[backfill] {len(videos)} videos queued "
              f"(concurrency={args.concurrency})", flush=True)
        sem = asyncio.Semaphore(max(1, args.concurrency))
        queue: asyncio.Queue = asyncio.Queue()
        for i, v in enumerate(videos, 1):
            queue.put_nowait((i, v))

        async def worker() -> None:
            while True:
                try:
                    i, v = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                await _one(v, sem, stats, f"{i}/{len(videos)}")
                queue.task_done()
                if args.sleep:
                    await asyncio.sleep(args.sleep)

        await asyncio.gather(*[worker() for _ in range(max(1, args.concurrency))])
    finally:
        await close_pool()
    print(f"[backfill] done: {stats}", flush=True)
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--max", type=int, default=200)
    p.add_argument("--sleep", type=int, default=15)
    p.add_argument("--concurrency", type=int, default=1)
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
