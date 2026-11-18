"""Hybrid search (vector + FTS + trigram) and transcript retrieval."""

from __future__ import annotations

import json
from typing import Any

from minuta import embeddings, store
from minuta.db import fetch_one, pool
from minuta.settings import get_settings


def _youtube_url(video_id: str, start_ms: int | None) -> str:
    base = f"https://www.youtube.com/watch?v={video_id}"
    return base if start_ms is None else f"{base}&t={start_ms // 1000}s"


async def search_transcripts(query: str, *, limit: int = 10, offset: int = 0,
                             language: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    limit = max(1, min(limit, settings.max_page_size))
    where: list[str] = ["tv.active"]
    params: dict = {"q": query}
    if language:
        where.append("tv.language = %(language)s")
        params["language"] = language
    vector = await embeddings.embed_query(query)
    params["vec"] = f"[{','.join(map(str, vector))}]"
    params["emodel"] = settings.embedding_model
    params["evers"] = settings.embedding_version
    # Same-transaction SET LOCAL: the vector CTE only touches rows embedded
    # with the active model/version, so a mid-migration mixed-dims table
    # can never abort search with a dimension-mismatch error.
    async with pool().connection() as conn:
        await conn.execute("SET LOCAL hnsw.ef_search = %s", (settings.hnsw_ef_search,))
        async with conn.cursor() as cur:
            await cur.execute(
                f"""with vec as (
              select ch.id, 1 - (ch.embedding <=> %(vec)s::vector) as similarity
              from chunks ch
              where ch.embedding_model = %(emodel)s
                and ch.embedding_version = %(evers)s
              order by ch.embedding <=> %(vec)s::vector limit 200
            )
           select ch.id, v.youtube_video_id, v.title as video_title, c.title as channel_title,
                  tv.language, tv.is_generated, ch.start_ms, ch.end_ms, ch.text,
                  coalesce(vec.similarity, 0) as similarity
           from chunks ch
           join videos v on v.id = ch.video_id
           join channels c on c.id = v.channel_id
           join transcript_versions tv on tv.id = ch.transcript_version_id
           left join vec on vec.id = ch.id
           where tv.active and {' and '.join(where)}
             and (ch.text_tsv @@ plainto_tsquery('english', %(q)s) or vec.id is not null)
           order by coalesce(vec.similarity, 0) desc
           limit {limit} offset {offset}""",
                params,
            )
            rows = await cur.fetchall()
    results = [{
        "passage_id": str(r["id"]), "text": r["text"], "video_id": r["youtube_video_id"],
        "video_title": r["video_title"], "channel_title": r["channel_title"],
        "language": r["language"], "is_generated": r["is_generated"],
        "start_ms": r["start_ms"], "end_ms": r["end_ms"],
        "video_url": _youtube_url(r["youtube_video_id"], r["start_ms"]),
        "score": round(float(r["similarity"] or 0), 6),
    } for r in rows]
    return {"results": results, "returned": len(results), "query": query}


async def get_transcript(video_ref: str, *, mode: str = "auto",
                         cursor: int | None = None, page_size: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    page_size = page_size or settings.max_transcript_page_segments
    video = await fetch_one(
        """select v.youtube_video_id, v.title, tv.segment_count, tv.word_count,
                  tv.r2_json_key, tv.is_timed from videos v
           join transcript_versions tv on tv.video_id = v.id and tv.active
           where v.youtube_video_id = %s""",
        (video_ref,),
    )
    if not video:
        raise ValueError("video not found or has no stored transcript")
    doc = json.loads((await store.get_bytes(video["r2_json_key"])).decode("utf-8"))
    segments = doc["segments"]
    if mode == "full" or (mode == "auto" and len(json.dumps(segments)) < settings.full_transcript_max_chars):
        return {"video_id": video["youtube_video_id"], "segments": segments,
                "complete": True, "is_timed": video["is_timed"]}
    start = int(cursor or 0)
    page = segments[start:start + page_size]
    end = start + len(page)
    return {"video_id": video["youtube_video_id"], "segments": page,
            "complete": False, "has_more": end < len(segments),
            "end_of_transcript": end >= len(segments),
            "next_cursor": end if end < len(segments) else None}
