#!/usr/bin/env python3
"""Sequential transcript backfill. One video at a time, checkpointed per video.

Usage: PYTHONPATH=src python scripts/backfill.py [--max 200] [--sleep 15]
Safe to stop and re-run at any time.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

sys.path.insert(0, "src")

from minuta import ingest
from minuta.db import close_pool, fetch_all, open_pool
from minuta.index import index_version


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
        print(f"[backfill] {len(videos)} videos queued", flush=True)
        for i, v in enumerate(videos, 1):
            try:
                res = await ingest.process_video(str(v["id"]))
            except Exception as exc:  # noqa: BLE001 - counted, loop continues
                stats["failed"] = stats.get("failed", 0) + 1
                print(f"[{i}/{len(videos)}] {v['youtube_video_id']} FAILED {type(exc).__name__}", flush=True)
                continue
            status = res.get("status", "?")
            stats[status] = stats.get(status, 0) + 1
            print(f"[{i}/{len(videos)}] {v['youtube_video_id']} {status}", flush=True)
            if status == "stored":
                idx = await index_version(res["version_id"])
                print(f"    indexed chunks={idx.get('chunks')}", flush=True)
            if i < len(videos):
                time.sleep(args.sleep)
    finally:
        await close_pool()
    print(f"[backfill] done: {stats}", flush=True)
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--max", type=int, default=200)
    p.add_argument("--sleep", type=int, default=15)
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
