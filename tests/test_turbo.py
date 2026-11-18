"""Offline tests for the TURBO (paid fastest) path. No network, no keys."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from minuta import embeddings, youtube
from minuta.settings import get_settings
from minuta.transcripts.base import (
    TranscriptProviderDisabled,
    TranscriptTemporaryError,
    TranscriptUnavailable,
)
from minuta.transcripts.pipeline import providers
from minuta.transcripts.remote import TranscriptApiProvider


def _tapi_ok(request):
    assert request.headers["authorization"] == "Bearer test-tapi-key"
    return httpx.Response(200, json={
        "video_id": "VID12345678", "language": "en",
        "transcript": [
            {"text": "hello world", "start": 1.0, "duration": 2.0},
            {"text": "second line", "start": 3.0, "duration": 1.5},
        ],
    })


def test_transcriptapi_maps_segments_to_ms():
    async def run():
        raw = await TranscriptApiProvider(
            "test-tapi-key", transport=httpx.MockTransport(_tapi_ok)
        ).fetch("VID12345678", ["en"])
        assert [(s.text, s.start_ms, s.end_ms) for s in raw.segments] == [
            ("hello world", 1000, 3000), ("second line", 3000, 4500)]
        assert raw.is_timed is True and raw.provider == "transcriptapi"

    asyncio.run(run())


@pytest.mark.parametrize("code", ["no_captions", "video_unavailable",
                                  "age_restricted",
                                  "no_transcript_for_requested_languages"])
def test_transcriptapi_definitive_404_is_permanent(code):
    def handler(request):
        return httpx.Response(404, json={"detail": "nope", "code": code})

    async def run():
        try:
            await TranscriptApiProvider(
                "t", transport=httpx.MockTransport(handler)).fetch("x", ["en"])
        except TranscriptUnavailable:
            return
        raise AssertionError("expected TranscriptUnavailable")

    asyncio.run(run())


def test_transcriptapi_live_not_started_retries():
    def handler(request):
        return httpx.Response(404, json={"detail": "soon", "code": "live_not_started"})

    async def run():
        try:
            await TranscriptApiProvider(
                "t", transport=httpx.MockTransport(handler)).fetch("x", ["en"])
        except TranscriptTemporaryError:
            return
        raise AssertionError("expected TranscriptTemporaryError")

    asyncio.run(run())


@pytest.mark.parametrize("status", [401, 402, 408, 422, 429, 503])
def test_transcriptapi_status_mapping(status):
    def handler(request):
        return httpx.Response(status, json={"detail": "e", "code": "x"})

    expected = (TranscriptProviderDisabled if status == 401
                else TranscriptUnavailable if status == 422
                else TranscriptTemporaryError)

    async def run():
        try:
            await TranscriptApiProvider(
                "t", transport=httpx.MockTransport(handler)).fetch("x", ["en"])
        except expected:
            return
        raise AssertionError(f"expected {expected} for {status}")

    asyncio.run(run())


def test_transcriptapi_disabled_without_token():
    async def run():
        try:
            await TranscriptApiProvider("").fetch("x", ["en"])
        except TranscriptProviderDisabled:
            return
        raise AssertionError("expected disabled")

    asyncio.run(run())


def test_pipeline_registers_transcriptapi_first():
    os.environ["TRANSCRIPT_PROVIDER_ORDER"] = "transcriptapi,supadata"
    os.environ["TRANSCRIPT_API_KEY"] = "k"
    get_settings.cache_clear()
    try:
        assert [p.name for p in providers()] == ["transcriptapi"]
    finally:
        del os.environ["TRANSCRIPT_PROVIDER_ORDER"]
        del os.environ["TRANSCRIPT_API_KEY"]
        get_settings.cache_clear()


def test_remote_embeddings_batch_through_mock():
    seen = []

    def handler(request):
        body = __import__("json").loads(request.content.decode())
        seen.append(body)
        n = len(body["input"])
        dims = body.get("dimensions", 4)
        return httpx.Response(200, json={
            "data": [{"embedding": [0.1 * (i + 1)] * dims} for i in range(n)]})

    os.environ.update({
        "EMBEDDING_PROVIDER": "openai",
        "EMBEDDING_API_KEY": "ek",
        "EMBEDDING_BASE_URL": "https://api.example.com/v1",
        "EMBEDDING_MODEL": "test-model",
        "EMBEDDING_DIMENSIONS": "4",
        "EMBEDDING_BATCH_SIZE": "2",
    })
    get_settings.cache_clear()
    try:
        vecs = embeddings.embed(["a", "b", "c"],
                                transport=httpx.MockTransport(handler))
    finally:
        for k in ("EMBEDDING_PROVIDER", "EMBEDDING_API_KEY",
                  "EMBEDDING_BASE_URL", "EMBEDDING_MODEL",
                  "EMBEDDING_DIMENSIONS", "EMBEDDING_BATCH_SIZE"):
            del os.environ[k]
        get_settings.cache_clear()
    assert len(seen) == 2  # batch of 2 + batch of 1
    assert seen[0]["dimensions"] == 4 and len(vecs) == 3
    assert all(len(v) == 4 for v in vecs)


def test_remote_embeddings_short_batch_raises():
    def handler(request):
        return httpx.Response(200, json={"data": []})

    os.environ.update({"EMBEDDING_PROVIDER": "openai", "EMBEDDING_API_KEY": "ek"})
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            embeddings.embed(["a"], transport=httpx.MockTransport(handler))
    finally:
        del os.environ["EMBEDDING_PROVIDER"]
        del os.environ["EMBEDDING_API_KEY"]
        get_settings.cache_clear()


def test_embedding_provider_rejects_unknown():
    import pydantic

    os.environ["EMBEDDING_PROVIDER"] = "telepathy"
    get_settings.cache_clear()
    try:
        with pytest.raises(pydantic.ValidationError):
            get_settings()
    finally:
        del os.environ["EMBEDDING_PROVIDER"]
        get_settings.cache_clear()


def test_youtube_keys_split_and_rotate():
    os.environ["YOUTUBE_API_KEY"] = "k1,k2"
    get_settings.cache_clear()
    try:
        assert get_settings().youtube_api_keys == ["k1", "k2"]
        assert {youtube._next_key(), youtube._next_key()} == {"k1", "k2"}
    finally:
        os.environ["YOUTUBE_API_KEY"] = "dummy-test-key"
        get_settings.cache_clear()


def test_backfill_args_default_sequential():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "backfill_mod", "scripts/backfill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import sys
    old = sys.argv
    sys.argv = ["backfill.py"]
    try:
        parsed = mod._parse_args()
    finally:
        sys.argv = old
    assert parsed.concurrency == 1 and parsed.sleep == 15
