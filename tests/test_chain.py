"""Offline checks for the provider chain's error precedence."""

from __future__ import annotations

import asyncio

from minuta.transcripts import pipeline
from minuta.transcripts.base import TranscriptTemporaryError, TranscriptUnavailable


def test_first_provider_disabled_falls_through():
    class Off:
        name = "supadata"

        async def fetch(self, video_id, languages):
            from minuta.transcripts.base import TranscriptProviderDisabled

            raise TranscriptProviderDisabled("no key")

    class Empty:
        name = "yta"

        async def fetch(self, video_id, languages):
            raise TranscriptUnavailable("nothing")

    orig = pipeline.providers
    pipeline.providers = lambda: [Off(), Empty()]  # noqa: E731
    try:
        asyncio.run(pipeline.fetch("x"))
    except pipeline.PermanentFailure:
        pass
    else:
        raise AssertionError("expected PermanentFailure")
    finally:
        pipeline.providers = orig


def test_auth_required_beats_everything():
    from minuta.transcripts.base import TranscriptAuthRequired

    class Locked:
        name = "ytdlp"

        async def fetch(self, video_id, languages):
            raise TranscriptAuthRequired("need cookies")

    class Blocked:
        name = "yta"

        async def fetch(self, video_id, languages):
            raise TranscriptTemporaryError("blocked")

    orig = pipeline.providers
    pipeline.providers = lambda: [Locked(), Blocked()]  # noqa: E731
    try:
        asyncio.run(pipeline.fetch("x"))
    except pipeline.AuthRequiredFailure:
        pass
    else:
        raise AssertionError("expected AuthRequiredFailure")
    finally:
        pipeline.providers = orig
