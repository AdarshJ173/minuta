"""Transcript provider contract and the canonical segment shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class TranscriptUnavailable(RuntimeError):
    """Definitive: this video has no usable captions (disabled, none, private, deleted)."""


class TranscriptTemporaryError(RuntimeError):
    """Transient: rate limiting, outage, network failure. Retry with backoff."""


class TranscriptProviderDisabled(RuntimeError):
    """Provider not configured or not permitted in this deployment."""


class TranscriptAuthRequired(RuntimeError):
    """Needs account authentication or cookies. Never retried automatically;
    a human must approve the credential first."""


@dataclass
class Segment:
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass
class RawTranscript:
    language: str
    segments: list[Segment]
    source: str
    provider: str
    is_generated: bool | None = None
    is_timed: bool = True
    raw_bytes: bytes | None = None
    raw_format: str = "json"
    raw_content_type: str = "application/json"
    metadata: dict = field(default_factory=dict)


class TranscriptProvider(Protocol):
    name: str

    def enabled(self) -> bool: ...

    async def fetch(self, video_id: str, languages: list[str]) -> RawTranscript: ...
