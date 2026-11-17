"""Offline unit tests: parsers, rolling dedupe, canonical docs, error mapping."""

from __future__ import annotations

import asyncio

import httpx

from minuta.transcripts import pipeline
from minuta.transcripts.apify import ApifyProvider
from minuta.transcripts.base import (
    RawTranscript,
    Segment,
    TranscriptAuthRequired,
    TranscriptProviderDisabled,
    TranscriptTemporaryError,
    TranscriptUnavailable,
)
from minuta.transcripts.text import (
    build_document,
    dedupe_rolling_captions,
    parse_markdown_transcript,
    parse_srt,
    parse_vtt,
)
from minuta.transcripts.ytdlp import YtDlpProvider


def test_vtt_preserves_cues_and_timestamps():
    vtt = "WEBVTT\n\n00:00:01.360 --> 00:00:04.000\nHello, <b>world</b>\n\n00:01:02.500 --> 00:01:05.000\nSecond\ncue\n"
    segs = parse_vtt(vtt)
    assert [(s.start_ms, s.end_ms, s.text) for s in segs] == [
        (1360, 4000, "Hello, world"),
        (62500, 65000, "Second\ncue"),
    ]


def test_srt_parses_comma_timestamps():
    srt = "1\n00:00:01,000 --> 00:00:03,500\nFirst\n\n2\n00:00:04,000 --> 00:00:06,000\nSecond\n"
    assert [s.start_ms for s in parse_srt(srt)] == [1000, 4000]


def test_markdown_untimed_invents_nothing():
    segs, timed = parse_markdown_transcript("Just a sentence.\nAnother one.\n")
    assert timed is False and all(s.start_ms is None for s in segs)


def test_rolling_overlap_stripped_but_repeats_kept():
    segs = [
        Segment(text="the most lucrative skill", start_ms=0, end_ms=2000),
        Segment(text="the most lucrative skill has always been", start_ms=2000, end_ms=4000),
        Segment(text="has always been capturing attention", start_ms=4000, end_ms=6000),
        Segment(text="no no no that is not what I meant", start_ms=6000, end_ms=9000),
    ]
    out = dedupe_rolling_captions(segs)
    assert [s.text for s in out] == [
        "the most lucrative skill", "has always been", "capturing attention",
        "no no no that is not what I meant",
    ]
    assert [s.start_ms for s in out] == [0, 2000, 4000, 6000]


def test_identical_cues_collapse_single_word_overlap_survives():
    assert len(dedupe_rolling_captions(
        [Segment(text="same line", start_ms=0, end_ms=1),
         Segment(text="same line", start_ms=1, end_ms=2)])) == 1
    out = dedupe_rolling_captions(
        [Segment(text="this is the end", start_ms=0, end_ms=1),
         Segment(text="end of the story", start_ms=1, end_ms=2)])
    assert out[1].text == "end of the story"


def test_canonical_doc_is_stable_and_timed():
    raw = RawTranscript(language="en", segments=[Segment(text="hi", start_ms=1000, end_ms=2000)],
                        source="s", provider="p", is_timed=True)
    kw = dict(video_id="v", video_title="t", channel_title="c",
              channel_youtube_id="UC", processing_version=1)
    first, second = build_document(raw, **kw), build_document(raw, **kw)
    assert first["_sha256"] == second["_sha256"]
    assert first["is_timed"] is True and "[00:00:01]" in first["_markdown"]


def test_ytdlp_prefers_manual_track_then_auto():
    provider = YtDlpProvider.__new__(YtDlpProvider)
    meta = {"language": "en", "subtitles": {"en": [{}]}, "automatic_captions": {"en": [{}]}}
    assert provider._choose_track(meta, ["en"])[1] is True
    auto_only = {"language": "en", "subtitles": {}, "automatic_captions": {"en": [{}]}}
    assert provider._choose_track(auto_only, ["en"])[1] is False


def test_ytdlp_error_mapping():
    provider = YtDlpProvider.__new__(YtDlpProvider)
    for stderr, exc in [
        ("sign in to confirm you're not a bot", TranscriptAuthRequired),
        ("HTTP Error 429 Too Many Requests", TranscriptTemporaryError),
        ("Video unavailable", TranscriptUnavailable),
    ]:
        try:
            provider._raise_for(1, f"ERROR: {stderr}", phase="subtitle")
        except exc:
            pass
        else:
            raise AssertionError(f"expected {exc} for {stderr!r}")


def _apify_ok(request):
    if request.url.path.endswith("/runs"):
        return httpx.Response(201, json={"data": {"id": "r", "defaultDatasetId": "d"}})
    if "actor-runs" in request.url.path:
        return httpx.Response(200, json={"data": {"status": "SUCCEEDED"}})
    return httpx.Response(200, json=[{
        "videoUrl": "https://www.youtube.com/watch?v=VID12345678",
        "videoDetails": {"videoId": "VID12345678"}, "languageCode": "en", "isGenerated": True,
        "transcript": [{"text": "hello world", "start": 1.0, "duration": 2.0}],
    }])


def test_apify_maps_segments_to_ms():
    async def run():
        raw = await ApifyProvider("tok", transport=httpx.MockTransport(_apify_ok)).fetch("VID12345678", ["en"])
        assert [(s.text, s.start_ms, s.end_ms) for s in raw.segments] == [("hello world", 1000, 3000)]
        assert raw.is_timed is True

    asyncio.run(run())


def test_apify_transcript_not_found_is_permanent():
    def handler(request):
        if request.url.path.endswith("/runs"):
            return httpx.Response(201, json={"data": {"id": "r", "defaultDatasetId": "d"}})
        if "actor-runs" in request.url.path:
            return httpx.Response(200, json={"data": {"status": "SUCCEEDED"}})
        return httpx.Response(200, json=[{
            "videoDetails": {"videoId": "VID12345678"}, "errorCode": "TranscriptNotFound"}])

    async def run():
        try:
            await ApifyProvider("t", transport=httpx.MockTransport(handler)).fetch("VID12345678", ["en"])
        except TranscriptUnavailable:
            return
        raise AssertionError("expected TranscriptUnavailable")

    asyncio.run(run())


def test_apify_inconclusive_is_temporary():
    def handler(request):
        if request.url.path.endswith("/runs"):
            return httpx.Response(201, json={"data": {"id": "r", "defaultDatasetId": "d"}})
        if "actor-runs" in request.url.path:
            return httpx.Response(200, json={"data": {"status": "SUCCEEDED"}})
        return httpx.Response(200, json=[
            {"videoDetails": {"videoId": "VID12345678"}, "errorCode": "RequestError"}])

    async def run():
        try:
            await ApifyProvider("t", transport=httpx.MockTransport(handler)).fetch("VID12345678", ["en"])
        except TranscriptTemporaryError:
            return
        raise AssertionError("expected TranscriptTemporaryError")

    asyncio.run(run())


def test_chain_primary_answer_beats_blocked_fallback():
    class Primary:
        name = "apify"

        async def fetch(self, video_id, languages):
            raise TranscriptUnavailable("no transcript")

    class Blocked:
        name = "yta"

        async def fetch(self, video_id, languages):
            raise TranscriptTemporaryError("provider blocked")

    orig = pipeline.providers
    pipeline.providers = lambda: [Primary(), Blocked()]  # noqa: E731
    try:
        asyncio.run(pipeline.fetch("x"))
    except pipeline.PermanentFailure as exc:
        assert "apify" in str(exc)
    else:
        raise AssertionError("expected PermanentFailure")
    finally:
        pipeline.providers = orig


def test_chain_primary_throttle_still_cools_down():
    class Throttled:
        name = "apify"

        async def fetch(self, video_id, languages):
            raise TranscriptTemporaryError("rate limited")

    class Blocked:
        name = "yta"

        async def fetch(self, video_id, languages):
            raise TranscriptTemporaryError("provider blocked")

    orig = pipeline.providers
    pipeline.providers = lambda: [Throttled(), Blocked()]  # noqa: E731
    try:
        asyncio.run(pipeline.fetch("x"))
    except pipeline.TemporaryFailure:
        pass
    else:
        raise AssertionError("expected TemporaryFailure")
    finally:
        pipeline.providers = orig


def test_disabled_provider_without_token():
    async def run():
        try:
            await ApifyProvider("").fetch("x", ["en"])
        except TranscriptProviderDisabled:
            return
        raise AssertionError("expected disabled")

    asyncio.run(run())
