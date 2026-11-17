"""Private R2 object storage. Keys derive from channel/video/language/hash."""

from __future__ import annotations

import boto3

from minuta.settings import get_settings

_client = None


def client():
    global _client
    if _client is None:
        s = get_settings()
        _client = boto3.client(
            "s3", endpoint_url=s.r2_endpoint, aws_access_key_id=s.r2_access_key_id,
            aws_secret_access_key=s.r2_secret_access_key, region_name=s.r2_region,
        )
    return _client


def transcript_keys(channel_yt: str, video_yt: str, language: str, sha: str) -> tuple[str, str]:
    base = f"transcripts/{channel_yt}/{video_yt}/{language}/{sha[:16]}"
    return f"{base}.json", f"{base}.md"


async def put_bytes(key: str, data: bytes, content_type: str, meta: dict | None = None) -> None:
    import asyncio

    s = get_settings()
    await asyncio.to_thread(
        client().put_object, Bucket=s.r2_bucket_name, Key=key, Body=data,
        ContentType=content_type, Metadata=meta or {},
    )


async def put_text(key: str, text: str, content_type: str, meta: dict | None = None) -> None:
    await put_bytes(key, text.encode("utf-8"), content_type, meta)


async def get_bytes(key: str) -> bytes:
    import asyncio

    s = get_settings()
    obj = await asyncio.to_thread(client().get_object, Bucket=s.r2_bucket_name, Key=key)
    return obj["Body"].read()
