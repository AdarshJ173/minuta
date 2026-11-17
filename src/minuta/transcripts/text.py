"""VTT / SRT / JSON / Markdown parsing, rolling-caption dedupe, canonical docs.

The canonical document is the only thing ever stored (R2) and indexed
(Supabase). Timestamps are preserved minuta; nothing is ever invented.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from minuta.transcripts.base import RawTranscript, Segment, TranscriptTemporaryError

SCHEMA_VERSION = 1
_WS = re.compile(r"\s+")


def _timestamp(ms: int | None) -> str:
    if ms is None:
        return "[--:--:--]"
    total = max(0, ms) // 1000
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"


def build_document(
    raw: RawTranscript,
    *,
    video_id: str,
    video_title: str,
    channel_title: str,
    channel_youtube_id: str,
    processing_version: int,
) -> dict[str, Any]:
    from minuta.transcripts.base import TranscriptUnavailable

    segments = [s for s in raw.segments if s.text and s.text.strip()]
    if not segments:
        raise TranscriptUnavailable("no non-empty transcript segments")

    is_timed = raw.is_timed and any(s.start_ms is not None for s in segments)
    joined = "\n".join(s.text for s in segments)
    duration_ms = next(
        (s.end_ms for s in reversed(segments) if s.end_ms is not None), None
    )

    doc = {
        "schema_version": SCHEMA_VERSION,
        "video_id": video_id,
        "video_title": video_title,
        "channel_id": channel_youtube_id,
        "channel_title": channel_title,
        "language": raw.language,
        "source": raw.source,
        "provider": raw.provider,
        "is_generated": raw.is_generated,
        "is_timed": is_timed,
        "segment_count": len(segments),
        "word_count": len(joined.split()),
        "duration_ms": duration_ms,
        "processing_version": processing_version,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "metadata": raw.metadata,
        "segments": [
            {
                "i": i,
                "start_ms": s.start_ms if is_timed else None,
                "end_ms": s.end_ms if is_timed else None,
                "text": s.text,
            }
            for i, s in enumerate(segments)
        ],
    }
    doc["_json_bytes"] = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
    doc["_sha256"] = content_hash(doc)
    doc["_markdown"] = render_markdown(doc)
    return doc


def content_hash(doc: dict[str, Any]) -> str:
    """Stable hash over content only: re-imports resolve to one version."""
    stable = {
        "schema_version": doc["schema_version"],
        "video_id": doc["video_id"],
        "language": doc["language"],
        "source": doc["source"],
        "provider": doc["provider"],
        "is_generated": doc["is_generated"],
        "is_timed": doc["is_timed"],
        "processing_version": doc["processing_version"],
        "segments": doc["segments"],
    }
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_markdown(doc: dict[str, Any]) -> str:
    lines = [
        f"# {doc['video_title']}",
        "",
        f"- Video: https://www.youtube.com/watch?v={doc['video_id']}",
        f"- Channel: {doc['channel_title']} ({doc['channel_id']})",
        f"- Language: {doc['language']}",
        f"- Source: {doc['source']} via {doc['provider']}"
        + (" (auto-generated)" if doc.get("is_generated") else ""),
        f"- Timing: {'timestamped' if doc['is_timed'] else 'untimed'}",
        f"- Segments: {doc['segment_count']} | Words: {doc['word_count']}",
        f"- Fetched: {doc['fetched_at']}",
        "",
    ]
    if not doc["is_timed"]:
        lines += [
            "> Untimed transcript: the source supplied no per-segment timestamps. "
            "No timestamps have been invented.",
            "",
        ]
    for seg in doc["segments"]:
        lines.append(f"{_timestamp(seg['start_ms'])} {seg['text']}" if doc["is_timed"] else seg["text"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_TS = (
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[.,](?P<ms>\d{1,3})"
    r"|(?P<m2>\d{1,2}):(?P<s2>\d{2})[.,](?P<ms2>\d{1,3})"
)
_TS_RE = re.compile(_TS)


def _parse_ts(value: str) -> int | None:
    m = _TS_RE.search(value.strip())
    if not m:
        return None
    g = m.groupdict()
    if g.get("h") is not None:
        h, mi, s, ms = int(g["h"]), int(g["m"]), int(g["s"]), int((g["ms"] or "0").ljust(3, "0"))
    else:
        h, mi, s, ms = 0, int(g["m2"]), int(g["s2"]), int((g["ms2"] or "0").ljust(3, "0"))
    return ((h * 3600 + mi * 60 + s) * 1000) + ms


def parse_cue_blocks(text: str) -> list[Segment]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    segments: list[Segment] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines or lines[0].strip().upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        arrow = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if arrow is None:
            continue
        start_raw, _, end_raw = lines[arrow].partition("-->")
        payload = [re.sub(r"<[^>]+>", "", ln) for ln in lines[arrow + 1 :]]
        content = "\n".join(payload).strip()
        if content:
            segments.append(Segment(text=content, start_ms=_parse_ts(start_raw), end_ms=_parse_ts(end_raw)))
    return segments


def parse_vtt(text: str) -> list[Segment]:
    if not (out := parse_cue_blocks(text)):
        raise ValueError("no VTT cues parsed")
    return out


def parse_srt(text: str) -> list[Segment]:
    if not (out := parse_cue_blocks(text)):
        raise ValueError("no SRT cues parsed")
    return out


def parse_import(filename: str, content: bytes) -> RawTranscript:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    from minuta.transcripts.base import TranscriptUnavailable

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TranscriptUnavailable("imported file is not valid UTF-8 text") from exc
    if suffix == "vtt":
        return RawTranscript(language="unknown", segments=parse_vtt(text),
                             source="import.vtt", provider="import", raw_bytes=content,
                             raw_format="vtt", raw_content_type="text/vtt")
    if suffix == "srt":
        return RawTranscript(language="unknown", segments=parse_srt(text),
                             source="import.srt", provider="import", raw_bytes=content,
                             raw_format="srt", raw_content_type="application/x-subrip")
    if suffix in ("md", "markdown", "txt"):
        segments, timed = parse_markdown_transcript(text)
        return RawTranscript(language="unknown", segments=segments,
                             source=f"import.{suffix}", provider="import", is_timed=timed,
                             raw_bytes=content, raw_format=suffix, raw_content_type="text/markdown")
    raise TranscriptTemporaryError(f"unsupported import format: {suffix or 'none'}")


_MD_TS_RE = re.compile(r"^\s*\[?(\d{1,2}):(\d{2})(?::(\d{2}))?(?:[.,](\d{1,3}))?\]?\s+(.*)$")


def parse_markdown_transcript(text: str) -> tuple[list[Segment], bool]:
    segments: list[Segment] = []
    timed = False
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", ">", "- ", "* ", "|")):
            continue
        if m := _MD_TS_RE.match(s):
            a, b, c, ms, content = m.groups()
            base = (int(a) * 3600 + int(b) * 60 + int(c)) if c else (int(a) * 60 + int(b))
            segments.append(Segment(text=content, start_ms=base * 1000 + int((ms or "0").ljust(3, "0"))))
            timed = True
        elif segments and segments[-1].end_ms is None:
            segments[-1].text = f"{segments[-1].text}\n{s}"
        else:
            segments.append(Segment(text=s))
    if not segments:
        raise ValueError("no transcript lines parsed from markdown")
    return segments, timed


def dedupe_rolling_captions(segments: list[Segment], *, min_overlap_words: int = 2) -> list[Segment]:
    """Strip only the boundary overlap of rolling auto-captions.

    For each adjacent pair, remove the longest suffix-of-previous that is a
    prefix of the current cue (word boundary, >= min_overlap_words). Repeats
    inside a cue or not at the boundary are preserved.
    """
    out: list[Segment] = []
    for seg in segments:
        text = _WS.sub(" ", seg.text.replace("\r", " ")).strip()
        if not text:
            continue
        if out and text != out[-1].text:
            prev, cur = out[-1].text.split(), text.split()
            if cur[: len(prev)] == prev and len(cur) > len(prev):
                text = " ".join(cur[len(prev):])
            else:
                for size in range(min(len(prev), len(cur), 30), min_overlap_words - 1, -1):
                    if prev[-size:] == cur[:size]:
                        text = " ".join(cur[size:])
                        break
                else:
                    pass
        if not text or (out and text == out[-1].text):
            continue
        out.append(Segment(text=text, start_ms=seg.start_ms, end_ms=seg.end_ms))
    return out
