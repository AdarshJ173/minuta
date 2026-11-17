"""Ingestion: discovery upserts, provider-chain fetch, R2 store, index enqueue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from minuta import jobs, provider_state, store, youtube
from minuta.db import fetch_one, pool
from minuta.logging import log
from minuta.settings import get_settings
from minuta.transcripts.base import RawTranscript
from minuta.transcripts.pipeline import (
    AuthRequiredFailure,
    PermanentFailure,
    TemporaryFailure,
)
from minuta.transcripts.pipeline import (
    fetch as fetch_raw,
)
from minuta.transcripts.text import build_document, parse_import


async def upsert_channel(client, raw_input: str) -> dict:
    from minuta.youtube import get_videos  # noqa: F401 (re-export surface)

    info = await youtube.resolve_channel(client, youtube.parse_channel_input(raw_input))
    async with pool().connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """insert into channels (youtube_channel_id, handle, title, description, uploads_playlist_id)
                   values (%(cid)s, %(handle)s, %(title)s, %(desc)s, %(uploads)s)
                   on conflict (youtube_channel_id) do update
                   set title=excluded.title, description=excluded.description, updated_at=now()
                   returning *""",
                {"cid": info["youtube_channel_id"], "handle": info.get("handle", ""),
                 "title": info["title"], "desc": info["description"],
                 "uploads": info["uploads_playlist_id"]},
            )
            return await cur.fetchone()


async def sync_channel(channel_id: str, *, max_videos: int | None = None) -> dict:
    import httpx

    settings = get_settings()
    channel = await fetch_one("select * from channels where id=%s", (channel_id,))
    if not channel or not channel["uploads_playlist_id"]:
        return {"status": "skipped"}
    max_videos = max_videos or settings.sync_max_videos_per_run
    stats = {"videos_seen": 0, "videos_new": 0, "jobs_enqueued": 0}
    cursor, seen = channel.get("discovery_cursor"), 0
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            page = await youtube.list_uploads_page(client, channel["uploads_playlist_id"], cursor)
            details = {d["youtube_video_id"]: d
                       for d in await youtube.get_videos(client, [i["youtube_video_id"] for i in page["items"]])}
            for item in page["items"]:
                if (detail := details.get(item["youtube_video_id"])) is None:
                    continue
                stats["videos_seen"] += 1
                async with pool().connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """insert into videos (channel_id, youtube_video_id, title, description,
                                                   published_at, availability)
                               values (%s,%s,%s,%s,%s,'available')
                               on conflict (youtube_video_id) do update set title=excluded.title
                               returning id, transcript_status""",
                            (channel["id"], detail["youtube_video_id"], detail["title"],
                             detail.get("description"), detail.get("published_at")),
                        )
                        row = await cur.fetchone()
                if row["transcript_status"] != "stored":
                    if await jobs.enqueue("transcript.fetch", {"video_id": str(row["id"])}, priority=60):
                        stats["jobs_enqueued"] += 1
                else:
                    stats["videos_new"] += 1
                seen += 1
                if seen >= max_videos:
                    return stats
            cursor = page["next_page_token"]
            if not cursor:
                return {**stats, "complete": True}


async def process_video(video_id: str) -> dict[str, Any]:
    settings = get_settings()
    video = await fetch_one(
        """select v.*, c.title as channel_title, c.youtube_channel_id from videos v
           join channels c on c.id = v.channel_id where v.id = %s""", (video_id,))
    if not video:
        raise PermanentFailure("video not found")
    if video["transcript_status"] == "stored":
        return {"status": "unchanged"}
    if video["transcript_attempts"] >= settings.transcript_max_attempts:
        return {"status": "unavailable", "reason": "max_attempts"}
    if await provider_state.get_cooldown("transcript"):
        return {"status": "deferred", "reason": "transcript provider cooling down"}
    try:
        raw = await fetch_raw(video["youtube_video_id"])
    except AuthRequiredFailure as exc:
        until = await provider_state.set_cooldown("transcript", 24 * 60, str(exc))
        return {"status": "blocked_auth", "reason": str(exc), "until": until.isoformat()}
    except TemporaryFailure as exc:
        if any(w in str(exc).lower() for w in ("block", "throttl", "exhausted", "429")):
            until = await provider_state.set_cooldown("transcript", 30, str(exc))
            await _defer(video_id, until)
            return {"status": "deferred", "reason": str(exc)[:200], "until": until.isoformat()}
        await _bump(video_id, str(exc), permanent=False)
        raise
    except PermanentFailure as exc:
        await _bump(video_id, str(exc), permanent=True)
        return {"status": "unavailable", "reason": str(exc)[:300]}
    version = await store_transcript(video, raw)
    await jobs.enqueue("transcript.index", {"version_id": str(version["id"])}, priority=50)
    return {"status": "stored", "version_id": str(version["id"])}


async def store_transcript(video: dict, raw: RawTranscript) -> dict:
    settings = get_settings()
    doc = build_document(
        raw, video_id=video["youtube_video_id"], video_title=video["title"],
        channel_title=video["channel_title"], channel_youtube_id=video["youtube_channel_id"],
        processing_version=settings.processing_version)
    json_key, md_key = store.transcript_keys(
        video["youtube_channel_id"], video["youtube_video_id"], doc["language"], doc["_sha256"])
    await store.put_bytes(json_key, doc["_json_bytes"], "application/json; charset=utf-8")
    await store.put_text(md_key, doc["_markdown"], "text/markdown; charset=utf-8")
    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("update transcript_versions set active=false where video_id=%s and active",
                                  (video["id"],))
                await cur.execute(
                    """insert into transcript_versions
                       (video_id, language, source, provider, is_generated, is_timed,
                        content_sha256, processing_version, segment_count, word_count,
                        duration_ms, r2_json_key, r2_markdown_key, size_bytes, active)
                       values (%(v)s,%(l)s,%(s)s,%(p)s,%(g)s,%(t)s,%(h)s,%(pv)s,%(n)s,%(w)s,%(d)s,%(j)s,%(m)s,%(z)s,true)
                       on conflict (video_id, language, content_sha256, processing_version)
                       do update set active=true returning *""",
                    {"v": video["id"], "l": doc["language"], "s": doc["source"], "p": doc["provider"],
                     "g": doc["is_generated"], "t": doc["is_timed"], "h": doc["_sha256"],
                     "pv": settings.processing_version, "n": doc["segment_count"],
                     "w": doc["word_count"], "d": doc["duration_ms"], "j": json_key,
                     "m": md_key, "z": len(doc["_json_bytes"])},
                )
                version = await cur.fetchone()
                await cur.execute(
                    """update videos set transcript_status='stored', transcript_attempts=0,
                       transcript_next_retry_at=null, indexing_status='pending' where id=%s""",
                    (video["id"],))
    log("transcript.stored", video_id=str(video["id"]),
        detail=f"{doc['segment_count']} segments, {doc['word_count']} words")
    return version


async def _defer(video_id: str, until: datetime) -> None:
    from minuta.db import execute

    await execute("update videos set transcript_next_retry_at=%s where id=%s", (until, video_id))


async def _bump(video_id: str, error: str, *, permanent: bool) -> None:
    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("select transcript_attempts from videos where id=%s", (video_id,))
                attempts = int((await cur.fetchone())["transcript_attempts"]) + 1
                if permanent:
                    delay, status = timedelta(days=7), "unavailable"
                else:
                    delay = timedelta(minutes=min(60 * 2**attempts, 24 * 60))
                    status = "failed"
                await cur.execute(
                    """update videos set transcript_status=%s, transcript_attempts=%s,
                       transcript_next_retry_at=%s, transcript_last_error=%s where id=%s""",
                    (status, attempts, datetime.now(UTC) + delay, error[:1500], video_id))


async def import_transcript(*, youtube_video_id: str, filename: str, content: bytes,
                            language: str | None = None) -> dict[str, Any]:
    raw = parse_import(filename, content)
    if language:
        raw.language = language
    video = await fetch_one("select * from videos where youtube_video_id=%s", (youtube_video_id,))
    if not video:
        raise PermanentFailure("video is not in the library; sync its channel first")
    channel = await fetch_one("select * from channels where id=%s", (video["channel_id"],))
    full = {**video, "channel_title": channel["title"],
            "youtube_channel_id": channel["youtube_channel_id"]}
    version = await store_transcript(full, raw)
    await jobs.enqueue("transcript.index", {"version_id": str(version["id"])}, priority=50)
    return {"version_id": str(version["id"]), "segments": version["segment_count"],
            "words": version["word_count"], "is_timed": version["is_timed"]}
