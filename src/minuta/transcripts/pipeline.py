"""Ordered provider chain with honest error semantics.

Two rules learned the hard way:
1. A chronically blocked fallback must never trigger a global cooldown when
   the primary provider already gave a definitive answer.
2. Only definitive per-video errors are permanent; everything inconclusive
   retries and is never recorded as "no transcript".
"""

from __future__ import annotations

from minuta.settings import get_settings
from minuta.transcripts.apify import ApifyProvider
from minuta.transcripts.base import (
    RawTranscript,
    TranscriptAuthRequired,
    TranscriptProviderDisabled,
    TranscriptTemporaryError,
    TranscriptUnavailable,
)
from minuta.transcripts.remote import SupadataProvider, YouTubeTranscriptApiProvider
from minuta.transcripts.ytdlp import YtDlpProvider


class PermanentFailure(RuntimeError):
    pass


class TemporaryFailure(RuntimeError):
    pass


class AuthRequiredFailure(RuntimeError):
    """A provider needs account authentication; never retried automatically."""


def providers() -> list:
    settings = get_settings()
    available = {
        "apify": ApifyProvider(settings.apify_api_token),
        "ytdlp": YtDlpProvider(),
        "yta": YouTubeTranscriptApiProvider(),
        "supadata": SupadataProvider(settings.supadata_api_key),
    }
    return [p for name in settings.tx_provider_order if (p := available.get(name)) and p.enabled()]


async def fetch(video_id: str) -> RawTranscript:
    """First provider in TRANSCRIPT_PROVIDER_ORDER that succeeds, wins."""
    settings = get_settings()
    chain = providers()
    if not chain:
        raise PermanentFailure("no transcript provider configured; check APIFY_API_TOKEN etc.")
    permanent, temporary, auth = [], [], []
    first_unavailable: str | None = None
    for index, provider in enumerate(chain):
        try:
            return await provider.fetch(video_id, settings.languages)
        except TranscriptProviderDisabled as exc:
            permanent.append(f"{provider.name}: disabled ({exc})")
        except TranscriptUnavailable as exc:
            permanent.append(f"{provider.name}: unavailable ({exc})")
            if index == 0:
                first_unavailable = f"{provider.name}: {exc}"
        except TranscriptAuthRequired as exc:
            auth.append(f"{provider.name}: {exc}")
        except TranscriptTemporaryError as exc:
            temporary.append(f"{provider.name}: {exc}")
    if auth:
        raise AuthRequiredFailure("; ".join(auth))
    if first_unavailable and not any(e.split(":", 1)[0] == chain[0].name for e in temporary):
        raise PermanentFailure(first_unavailable)
    if temporary:
        raise TemporaryFailure("; ".join(temporary))
    raise PermanentFailure("; ".join(permanent) or "no transcript found")
