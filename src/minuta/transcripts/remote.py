"""Unofficial caption providers: youtube-transcript-api and Supadata."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from minuta.logging import log
from minuta.transcripts.base import (
    RawTranscript,
    Segment,
    TranscriptProviderDisabled,
    TranscriptTemporaryError,
    TranscriptUnavailable,
)


class YouTubeTranscriptApiProvider:
    """Best-effort captions via youtube-transcript-api.

    Unofficial and frequently IP-blocked from datacenters; failures surface
    as temporary so the worker backs off instead of hammering.
    """

    name = "yta"

    def enabled(self) -> bool:
        return True

    async def fetch(self, video_id: str, languages: list[str]) -> RawTranscript:
        return await asyncio.to_thread(self._fetch_sync, video_id, languages)

    def _fetch_sync(self, video_id: str, languages: list[str]) -> RawTranscript:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            from youtube_transcript_api import _errors as yt_errors
        except Exception as exc:
            raise TranscriptProviderDisabled(f"youtube-transcript-api missing: {exc}") from exc

        def _classes(*names: str) -> tuple[type[Exception], ...]:
            return tuple(
                c for n in names
                if isinstance((c := getattr(yt_errors, n, None)), type) and issubclass(c, Exception)
            )

        permanent = _classes("TranscriptsDisabled", "NoTranscriptFound", "VideoUnavailable",
                             "VideoUnplayable", "AgeRestricted", "InvalidVideoId")
        throttled = _classes("IpBlocked", "RequestBlocked", "YouTubeRequestFailed", "HTTPError")

        api = YouTubeTranscriptApi()
        try:
            candidates = list(api.list(video_id))
            wanted = [lang.lower() for lang in languages]
            chosen = next(
                (c for c in candidates if c.language_code.lower() in wanted and not c.is_generated),
                next((c for c in candidates if c.language_code.lower() in wanted), None),
            ) or (candidates[0] if candidates else None)
            if chosen is None:
                raise TranscriptUnavailable("no transcript tracks offered")
            fetched = chosen.fetch()
            segments = [
                Segment(text=(sn.text or "").strip(),
                        start_ms=int(round(float(sn.start) * 1000)),
                        end_ms=int(round(float(sn.start) * 1000)) + int(round(float(getattr(sn, "duration", 0) or 0) * 1000)))
                for sn in fetched if (sn.text or "").strip()
            ]
            if not segments:
                raise TranscriptUnavailable("transcript track was empty")
            return RawTranscript(
                language=chosen.language_code, segments=segments,
                source="youtube.captions", provider=self.name,
                is_generated=bool(chosen.is_generated), is_timed=True,
                raw_bytes=json.dumps(
                    [{"i": i, "start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.text}
                     for i, s in enumerate(segments)], ensure_ascii=False).encode(),
                raw_format="json",
                metadata={"track_kind": "asr" if chosen.is_generated else "manual"},
            )
        except permanent as exc:
            raise TranscriptUnavailable(type(exc).__name__) from exc
        except throttled as exc:
            log("transcript.provider_throttled", video_id=video_id, detail=type(exc).__name__)
            raise TranscriptTemporaryError(f"provider blocked: {type(exc).__name__}") from exc
        except TranscriptUnavailable:
            raise
        except Exception as exc:
            raise TranscriptTemporaryError(f"{type(exc).__name__}: {exc}") from exc


class TranscriptApiProvider:
    """Fastest paid captions (transcriptapi.com): realtime REST, ~49ms median.

    Enabled only when TRANSCRIPT_API_KEY is set. Error mapping follows
    https://transcriptapi.com/docs/api: 404 codes are definitive except
    live_not_started (retry after airing); 408/429/5xx are transient;
    401 means the key is bad (disabled); 402 means credits ran out.
    """

    name = "transcriptapi"
    _API = "https://transcriptapi.com/api/v2"

    _DEFINITIVE_404 = frozenset({
        "no_captions", "video_unavailable", "age_restricted",
        "no_transcript_for_requested_languages",
    })

    def __init__(self, api_key: str = "", *, transport=None) -> None:
        self.api_key = api_key
        self._transport = transport

    def enabled(self) -> bool:
        return bool(self.api_key)

    async def fetch(self, video_id: str, languages: list[str]) -> RawTranscript:
        import httpx

        if not self.api_key:
            raise TranscriptProviderDisabled("TRANSCRIPT_API_KEY is not set")
        langs = ",".join((languages or ["en"])[:10])
        async with httpx.AsyncClient(timeout=30, transport=self._transport) as client:
            resp = await client.get(
                f"{self._API}/youtube/transcript",
                params={"video_url": video_id, "language": langs},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        if resp.status_code == 200:
            return self._to_raw(resp.json())
        if resp.status_code == 401:
            raise TranscriptProviderDisabled("transcriptapi rejected the API key")
        if resp.status_code == 402:
            raise TranscriptTemporaryError("transcriptapi plan exhausted; top up credits")
        if resp.status_code in (408, 429, 500, 502, 503, 504):
            raise TranscriptTemporaryError(f"transcriptapi {resp.status_code}")
        if resp.status_code == 404:
            try:
                code = str(resp.json().get("code") or "")
            except Exception:
                code = ""
            if code == "live_not_started":
                raise TranscriptTemporaryError("transcriptapi: live stream has not aired yet")
            if code in self._DEFINITIVE_404 or not code:
                raise TranscriptUnavailable(f"transcriptapi 404: {code or 'no transcript'}")
            raise TranscriptUnavailable(f"transcriptapi 404: {code}")
        if resp.status_code >= 400:
            raise TranscriptUnavailable(f"transcriptapi {resp.status_code}: {resp.text[:200]}")
        raise TranscriptTemporaryError(f"transcriptapi unexpected {resp.status_code}")

    @staticmethod
    def _to_raw(payload: dict[str, Any]) -> RawTranscript:
        segments: list[Segment] = []
        for item in payload.get("transcript") or []:
            if not isinstance(item, dict):
                continue
            if not (text := str(item.get("text", "") or "").strip()):
                continue
            try:
                start_ms = int(round(float(item.get("start", 0)) * 1000))
                duration_ms = int(round(float(item.get("duration", 0) or 0) * 1000))
            except (TypeError, ValueError):
                continue
            segments.append(Segment(text=text, start_ms=start_ms, end_ms=start_ms + duration_ms))
        if not segments:
            raise TranscriptUnavailable("transcriptapi returned no usable segments")
        language = str(payload.get("language") or "en")
        return RawTranscript(
            language=language, segments=segments,
            source="transcriptapi", provider="transcriptapi",
            is_generated=language.startswith("asr"), is_timed=True,
            raw_bytes=json.dumps(payload).encode(), raw_format="json",
        )


class SupadataProvider:
    """Optional paid API. Enabled only when SUPADATA_API_KEY is set."""

    name = "supadata"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    def enabled(self) -> bool:
        return bool(self.api_key)

    async def fetch(self, video_id: str, languages: list[str]) -> RawTranscript:
        import httpx

        if not self.api_key:
            raise TranscriptProviderDisabled("SUPADATA_API_KEY is not set")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                "https://api.supadata.ai/v1/youtube/transcript",
                params={"videoId": video_id, "lang": (languages or ["en"])[0]},
                headers={"x-api-key": self.api_key},
            )
        if resp.status_code == 404:
            raise TranscriptUnavailable("supadata: transcript not found")
        if resp.status_code in (429, 500, 502, 503, 504):
            raise TranscriptTemporaryError(f"supadata {resp.status_code}")
        if resp.status_code >= 400:
            raise TranscriptUnavailable(f"supadata {resp.status_code}: {resp.text[:200]}")
        payload: dict[str, Any] = resp.json()
        content = payload.get("content") or []
        segments: list[Segment] = []
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                start_ms = int(float(item.get("offset", item.get("start", 0)) or 0))
                duration_ms = int(float(item.get("duration", 0) or 0))
                if (text := str(item.get("text", "")).strip()):
                    segments.append(Segment(text=text, start_ms=start_ms, end_ms=start_ms + duration_ms))
        elif isinstance(content, str):
            segments.append(Segment(text=content))
        if not segments:
            raise TranscriptUnavailable("supadata returned no segments")
        return RawTranscript(
            language=payload.get("lang") or languages[0], segments=segments,
            source="supadata", provider=self.name,
            is_timed=any(s.start_ms is not None for s in segments),
            raw_bytes=json.dumps(payload).encode(), raw_format="json",
        )
