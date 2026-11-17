"""Subtitle-only extraction through yt-dlp. No media is ever downloaded.

Flow: probe with ``-J``, pick the original-language manual track (else the
original-language auto track), download only that one language as VTT.
The YouTube Data API key is never passed to yt-dlp.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from minuta.logging import log
from minuta.settings import get_settings
from minuta.transcripts.base import (
    RawTranscript,
    TranscriptAuthRequired,
    TranscriptProviderDisabled,
    TranscriptTemporaryError,
    TranscriptUnavailable,
)
from minuta.transcripts.text import dedupe_rolling_captions, parse_srt, parse_vtt

logger = logging.getLogger("minuta.ytdlp")
_URL_RE = re.compile(r"https?://\S+")
_lock = asyncio.Lock()


def _redact(text: str, limit: int = 400) -> str:
    return re.sub(r"\s+", " ", _URL_RE.sub("<url>", text or "")).strip()[:limit]


def _base(code: str | None) -> str:
    return (code or "en").replace("_", "-").split("-")[0].lower()


class YtDlpProvider:
    name = "ytdlp"

    def __init__(self) -> None:
        self.sleep_seconds = int(os.environ.get("YTDLP_SUBTITLE_SLEEP_SECONDS", "60"))
        self.max_retries = int(os.environ.get("YTDLP_MAX_RETRIES", "2"))
        self.timeout = int(os.environ.get("YTDLP_TIMEOUT_SECONDS", "240"))
        self.languages = get_settings().languages

    def enabled(self) -> bool:
        return shutil.which("yt-dlp") is not None

    async def fetch(self, video_id: str, languages: list[str]) -> RawTranscript:
        if not self.enabled():
            raise TranscriptProviderDisabled("yt-dlp is not installed")
        meta = await self._probe(video_id)
        language, is_manual, track = self._choose_track(meta, languages)
        path = await self._download(video_id, track, is_manual)
        try:
            suffix = path.suffix.lower()
            raw = path.read_text(encoding="utf-8", errors="replace")
            segments = parse_vtt(raw) if suffix == ".vtt" else parse_srt(raw)
            payload, fmt = path.read_bytes(), suffix.lstrip(".")
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)
        if not segments:
            raise TranscriptUnavailable("yt-dlp produced an empty subtitle file")
        if not is_manual:
            segments = dedupe_rolling_captions(segments)
        return RawTranscript(
            language=language, segments=segments, source="youtube.ytdlp.captions",
            provider=self.name, is_generated=not is_manual, is_timed=True,
            raw_bytes=payload, raw_format=fmt,
            metadata={"track_lang": track, "track_kind": "manual" if is_manual else "asr"},
        )

    async def _probe(self, video_id: str) -> dict[str, Any]:
        code, out, err = await self._run(
            [*_cmd(), "--ignore-config", "--no-warnings", "--no-playlist",
             "--skip-download", "-J", f"https://www.youtube.com/watch?v={video_id}"],
            timeout=120,
        )
        if code != 0 or not out.strip():
            self._raise_for(code, err, phase="probe")
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            raise TranscriptTemporaryError("yt-dlp returned unparsable metadata") from exc

    def _choose_track(self, meta: dict[str, Any], languages: list[str]) -> tuple[str, bool, str]:
        manual, auto = meta.get("subtitles") or {}, meta.get("automatic_captions") or {}
        original = meta.get("language") or meta.get("default_audio_language")
        wanted = [lang.lower() for lang in (languages or ["en"])]

        def pick(tracks: dict, prefs: list[str]) -> str | None:
            for pref in prefs:
                for key in tracks:
                    if key.lower() == pref or _base(key) == pref:
                        return key
            return None

        prefs = ([original.lower(), _base(original)] if original else []) + wanted + [_base(wanted[0])]
        if key := pick(manual, prefs):
            return (original if original and _base(original) == _base(key) else key), True, key
        if key := pick(auto, prefs):
            return (original if original and _base(original) == _base(key) else key), False, key
        if not manual and not auto:
            raise TranscriptUnavailable("no subtitle tracks offered")
        raise TranscriptUnavailable("no original-language subtitle track")

    async def _download(self, video_id: str, track_lang: str, is_manual: bool) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix=f"ytdlp-{video_id}-"))
        cmd = [*_cmd(), "--ignore-config", "--no-warnings", "--no-playlist", "--skip-download",
               "--write-subs" if is_manual else "--write-auto-subs",
               "--sub-langs", track_lang, "--sub-format", "vtt/srt/best",
               "--sleep-subtitles", str(self.sleep_seconds), "--retries", str(self.max_retries),
               "--no-progress", "-o", str(tmp / "%(id)s.%(ext)s"),
               f"https://www.youtube.com/watch?v={video_id}"]
        async with _lock:
            code, _out, err = await self._run(cmd, timeout=self.timeout)
        files = sorted(p for p in tmp.iterdir() if p.suffix.lower() in (".vtt", ".srt"))
        if code != 0 or not files:
            shutil.rmtree(tmp, ignore_errors=True)
            self._raise_for(code, err, phase="subtitle")
        log("ytdlp.subtitle_downloaded", video_id=video_id, detail=files[0].name)
        return files[0]

    async def _run(self, cmd: list[str], timeout: int) -> tuple[int, str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError as exc:
            raise TranscriptProviderDisabled("yt-dlp binary missing") from exc
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise TranscriptTemporaryError(f"yt-dlp timed out after {timeout}s") from exc
        return proc.returncode or 0, out_b.decode("utf-8", "replace"), err_b.decode("utf-8", "replace")

    def _raise_for(self, code: int, stderr: str, *, phase: str) -> None:
        text, detail = (stderr or "").lower(), _redact(stderr)
        logger.info("ytdlp failure phase=%s code=%s detail=%s", phase, code, detail)
        if "429" in text or "too many requests" in text:
            raise TranscriptTemporaryError("subtitle endpoint rate limited (HTTP 429)")
        if any(s in text for s in ("sign in to confirm", "not a bot", "login required",
                                   "use --cookies", "confirm your age")):
            raise TranscriptAuthRequired("YouTube requires account authentication or cookies")
        if any(s in text for s in ("no subtitle", "there are no subtitles", "no captions")) \
                or ("requested format is not available" in text and "subtitle" in text):
            raise TranscriptUnavailable("no captions available for this video")
        if any(s in text for s in ("video unavailable", "private video", "has been removed",
                                   "this video is unavailable")):
            raise TranscriptUnavailable("video unavailable")
        if "unable to extract" in text or "player response" in text:
            raise TranscriptTemporaryError(f"yt-dlp extractor error: {detail}")
        raise TranscriptTemporaryError(f"yt-dlp failed ({phase}): {detail}")


def _cmd() -> list[str]:
    if binary := shutil.which("yt-dlp"):
        return [binary]
    return [sys.executable, "-m", "yt_dlp"]
