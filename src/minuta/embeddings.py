"""Embeddings: local ONNX by default, OpenAI-compatible API when paid.

`EMBEDDING_PROVIDER=local` uses BGE-small via fastembed/ONNX: no key, no
network, no training. `EMBEDDING_PROVIDER=openai` posts to an
OpenAI-compatible `/v1/embeddings` endpoint (OpenAI, Voyage, TEI,
OpenRouter): ~50ms vs seconds per batch on CPU, at ~$0.02/1M tokens.
See docs/TURBO.md. Switching models/dims requires migration 002 and a
re-embed with bumped EMBEDDING_VERSION + PROCESSING_VERSION.
"""

from __future__ import annotations

from functools import lru_cache

from minuta.settings import get_settings


@lru_cache
def model():
    from fastembed import TextEmbedding

    settings = get_settings()
    return TextEmbedding(model_name=settings.embedding_model)


def embed(texts: list[str], *, transport=None) -> list[list[float]]:
    """Embed a batch. `transport` is a test hook (httpx.MockTransport)."""
    settings = get_settings()
    if settings.embedding_provider == "openai":
        return _embed_remote(texts, transport=transport)
    vectors = list(model().embed(texts, batch_size=settings.embedding_batch_size))
    return [list(map(float, v)) for v in vectors]


def _embed_remote(texts: list[str], *, transport=None) -> list[list[float]]:
    import httpx

    settings = get_settings()
    if not settings.embedding_api_key:
        raise ValueError("EMBEDDING_PROVIDER=openai needs EMBEDDING_API_KEY")
    url = settings.embedding_base_url.rstrip("/") + "/embeddings"
    headers = {"Authorization": f"Bearer {settings.embedding_api_key}"}
    out: list[list[float]] = []
    batch = max(1, settings.embedding_batch_size)
    with httpx.Client(timeout=120, transport=transport) as client:
        for i in range(0, len(texts), batch):
            payload: dict = {"model": settings.embedding_model, "input": texts[i:i + batch]}
            # Matryoshka-capable models (text-embedding-3-*, Voyage 4) truncate
            # server-side; harmless to send for others that ignore it.
            if settings.embedding_dimensions:
                payload["dimensions"] = settings.embedding_dimensions
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"embedding API transient {resp.status_code}")
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if len(data) != len(texts[i:i + batch]):
                raise RuntimeError("embedding API returned a short batch")
            out.extend([list(map(float, row["embedding"])) for row in data])
    return out


async def embed_query(text: str) -> list[float]:
    import asyncio

    return (await asyncio.to_thread(embed, [text]))[0]
