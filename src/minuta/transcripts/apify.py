"""Captions via the Apify Store actor ``supreme_coder/youtube-transcript-scraper``.

One Actor run per video, sequential, timestamped JSON output. Costs about
$0.70 per 1,000 transcripts against the Apify plan's included usage (the $0
plan includes $5/month, no card required; free-plan overage blocks instead
of charging, so it can never surprise-bill).

Only definitive actor errors (no captions, removed, age-restricted) are
permanent. Everything inconclusive retries and never becomes "no transcript".
"""

from __future__ import annotations

import asyncio

from minuta.logging import log
from minuta.transcripts.base import (
    RawTranscript,
    Segment,
    TranscriptProviderDisabled,
    TranscriptTemporaryError,
    TranscriptUnavailable,
)

ACTOR_ID = "supreme_coder~youtube-transcript-scraper"
_API = "https://api.apify.com/v2"

_DEFINITIVE = frozenset(
    {"TranscriptNotFound", "VideoUnavailable", "AgeRestricted", "URL_NOT_SUPPORTED"}
)


class ApifyProvider:
    name = "apify"

    def __init__(self, api_token: str = "", *, transport=None) -> None:
        self.api_token = api_token
        self._transport = transport

    def enabled(self) -> bool:
        return bool(self.api_token)

    async def fetch(self, video_id: str, languages: list[str]) -> RawTranscript:
        import httpx

        if not self.api_token:
            raise TranscriptProviderDisabled("APIFY_API_TOKEN is not set")
        headers = {"Authorization": f"Bearer {self.api_token}"}
        url = f"https://www.youtube.com/watch?v={video_id}"
        async with httpx.AsyncClient(timeout=60, transport=self._transport) as client:
            run = await client.post(
                f"{_API}/acts/{ACTOR_ID}/runs", headers=headers,
                json={"urls": [{"url": url}], "outputFormat": "json",
                      "languages": [(languages or ["en"])[0]]},
            )
            if run.status_code in (401, 403):
                raise TranscriptProviderDisabled("Apify rejected the API token")
            if run.status_code == 402:
                raise TranscriptTemporaryError("Apify plan usage exhausted; blocked until next cycle")
            if run.status_code >= 400:
                raise TranscriptTemporaryError(f"Apify start-run {run.status_code}: {run.text[:200]}")
            data = run.json().get("data", {})
            if not data.get("id") or not data.get("defaultDatasetId"):
                raise TranscriptTemporaryError("Apify start-run missing ids")
            await self._await(client, headers, data["id"], video_id)
            item = await self._item(client, headers, data["defaultDatasetId"], video_id)
        return self._to_raw(item)

    async def _await(self, client, headers: dict, run_id: str, video_id: str) -> None:
        waited, delay, deadline = 0, 10, 600
        while True:
            resp = await client.get(f"{_API}/actor-runs/{run_id}", headers=headers)
            if resp.status_code >= 400:
                raise TranscriptTemporaryError(f"Apify run status {resp.status_code}")
            status = resp.json().get("data", {}).get("status")
            if status == "SUCCEEDED":
                return
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                raise TranscriptTemporaryError(f"Apify run {run_id} ended with {status}")
            if waited >= deadline:
                raise TranscriptTemporaryError(f"Apify run {run_id} timed out")
            await asyncio.sleep(delay)
            waited += delay
            delay = min(delay + 5, 30)
            log("apify.run_waiting", video_id=video_id, detail=f"status={status} waited={waited}s")

    async def _item(self, client, headers: dict, dataset_id: str, video_id: str) -> dict:
        resp = await client.get(f"{_API}/datasets/{dataset_id}/items", headers=headers)
        if resp.status_code >= 400:
            raise TranscriptTemporaryError(f"Apify dataset read {resp.status_code}")
        for item in resp.json() if isinstance(resp.json(), list) else []:
            if not isinstance(item, dict):
                continue
            details = item.get("videoDetails") or {}
            ids = {details.get("videoId"),
                   (item.get("videoUrl") or "").rstrip("/").rsplit("v=", 1)[-1][:11]}
            if video_id not in ids:
                continue
            if item.get("transcript"):
                return item
            code = str(item.get("errorCode") or item.get("error") or "")
            if code in _DEFINITIVE or "TranscriptNotFound" in code:
                raise TranscriptUnavailable(f"apify: {code or 'no transcript'}")
            raise TranscriptTemporaryError(f"apify inconclusive for this video: {code[:150]}")
        raise TranscriptTemporaryError("apify returned no transcript item for this video")

    @staticmethod
    def _to_raw(item: dict) -> RawTranscript:
        segments: list[Segment] = []
        for seg in item.get("transcript") or []:
            if not isinstance(seg, dict) or not str(seg.get("text", "")).strip():
                continue
            try:
                start_ms = int(round(float(seg.get("start", 0)) * 1000))
                duration_ms = int(round(float(seg.get("duration", 0)) * 1000))
            except (TypeError, ValueError):
                continue
            segments.append(Segment(text=str(seg["text"]).strip(),
                                    start_ms=start_ms, end_ms=start_ms + duration_ms))
        if not segments:
            raise TranscriptUnavailable("apify transcript had no usable segments")
        return RawTranscript(
            language=item.get("languageCode") or "en", segments=segments,
            source="apify.transcript-scraper", provider="apify",
            is_generated=item.get("isGenerated"), is_timed=True,
            raw_format="json", metadata={"actor": ACTOR_ID},
        )
