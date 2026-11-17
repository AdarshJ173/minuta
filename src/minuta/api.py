"""REST API: public read/research routes plus scoped admin routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from minuta import auth, ingest, jobs, search
from minuta.settings import get_settings


class ChannelRequest(BaseModel):
    input: str = Field(min_length=2)


class KeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["read"])


async def _principal(authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not (p := await auth.principal(token)):
        raise HTTPException(401, {"code": "unauthorized", "message": "bad or missing token"})
    return p


def _need(*scopes: str):
    async def guard(p: dict = Depends(_principal)) -> dict:
        if auth.ADMIN in p["scopes"] or any(s in p["scopes"] for s in scopes):
            return p
        raise HTTPException(403, {"code": "forbidden", "message": "missing scope"})
    return guard


def build() -> FastAPI:
    app = FastAPI(title="Minuta", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    @app.get("/readyz")
    async def readyz() -> dict:
        from minuta import embeddings, store
        from minuta.db import fetch_one, open_pool

        await open_pool()
        await fetch_one("select 1")
        await embeddings.embed_query("ok")
        return {"db": True, "embeddings": True, "r2": True, "store": store.client() is not None}

    @app.get("/v1/search")
    async def v1_search(q: str, limit: int = Query(20, le=100), _: dict = Depends(_need(auth.READ))):
        return await search.search_transcripts(query=q, limit=limit)

    @app.get("/v1/videos/{video_id}/transcript")
    async def v1_transcript(video_id: str, mode: str = "auto", cursor: int | None = None,
                            page_size: int | None = None, _: dict = Depends(_need(auth.READ))):
        try:
            return await search.get_transcript(video_id, mode=mode, cursor=cursor, page_size=page_size)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/admin/channels", status_code=201)
    async def admin_channels(payload: ChannelRequest, _: dict = Depends(_need(auth.ADMIN))):
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            channel = await ingest.upsert_channel(client, payload.input)
        await jobs.enqueue("channel.sync", {"channel_id": str(channel["id"])}, priority=40)
        return {"channel_id": str(channel["id"]), "title": channel["title"]}

    @app.post("/admin/videos/{video_id}/refresh", status_code=202)
    async def admin_refresh(video_id: str, _: dict = Depends(_need(auth.ADMIN))):
        from minuta.db import execute, fetch_one

        row = await fetch_one("select id from videos where youtube_video_id=%s", (video_id,))
        if not row:
            raise HTTPException(404, "video not found")
        await execute(
            "update videos set transcript_status='pending', transcript_attempts=0,"
            " transcript_next_retry_at=null where id=%s", (row["id"],))
        job_id = await jobs.enqueue("transcript.fetch", {"video_id": str(row["id"])}, priority=30)
        return {"video_id": video_id, "job_id": job_id}

    @app.post("/admin/keys", status_code=201)
    async def admin_keys(payload: KeyRequest, _: dict = Depends(_need(auth.ADMIN))):
        return await auth.create_key(payload.name, payload.scopes)

    @app.get("/.well-known/minuta")
    async def well_known() -> dict:
        s = get_settings()
        return {"name": "minuta", "mcp": f"{s.public_base_url}/mcp",
                "auth": "Bearer token required on /v1, /admin and /mcp"}

    return app


app = build()


@app.exception_handler(Exception)
async def _unhandled(_request, exc: Exception) -> JSONResponse:
    from minuta.logging import log

    log("api.unhandled", detail=f"{type(exc).__name__}")
    return JSONResponse({"code": "internal", "message": "internal error"}, status_code=500)
