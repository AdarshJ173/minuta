"""Index a stored transcript version: chunk, embed, write chunks + FTS vectors."""

from __future__ import annotations

import json

from minuta import chunks as chunking
from minuta import embeddings, store
from minuta.db import fetch_one, pool
from minuta.logging import log
from minuta.settings import get_settings


async def index_version(version_id: str) -> dict:
    version = await fetch_one("select * from transcript_versions where id=%s", (version_id,))
    if not version:
        raise ValueError("version not found")
    video = await fetch_one("select * from videos where id=%s", (version["video_id"],))
    raw = json.loads((await store.get_bytes(version["r2_json_key"])).decode("utf-8"))
    texts = chunking.chunk("\n".join(s["text"] for s in raw["segments"]))
    vectors = await __import__("asyncio").to_thread(embeddings.embed, texts)
    settings = get_settings()
    async with pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("delete from chunks where transcript_version_id=%s", (version_id,))
                for pos, (text, vec) in enumerate(zip(texts, vectors, strict=True)):
                    seg = raw["segments"][min(pos, len(raw["segments"]) - 1)]
                    await cur.execute(
                        """insert into chunks
                           (video_id, transcript_version_id, position, text, embedding,
                            start_ms, end_ms, embedding_model, embedding_version)
                           values (%s,%s,%s,%s,%s::vector,%s,%s,%s,%s)""",
                        (video["id"], version_id, pos, text, f"[{','.join(map(str, vec))}]",
                         seg.get("start_ms"), seg.get("end_ms"),
                         settings.embedding_model, settings.embedding_version),
                    )
                await cur.execute(
                    "update videos set indexing_status='indexed' where id=%s", (video["id"],))
    log("transcript.indexed", version_id=version_id, detail=f"{len(texts)} chunks")
    return {"status": "indexed", "chunks": len(texts), "version_id": version_id}
