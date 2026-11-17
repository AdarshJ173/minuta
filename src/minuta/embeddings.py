"""Local ONNX embeddings (BGE-small, 384-d). No API key, no training, no network."""

from __future__ import annotations

from functools import lru_cache

from minuta.settings import get_settings


@lru_cache
def model():
    from fastembed import TextEmbedding

    settings = get_settings()
    return TextEmbedding(model_name=settings.embedding_model)


def embed(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    vectors = list(model().embed(texts, batch_size=settings.embedding_batch_size))
    return [list(map(float, v)) for v in vectors]


async def embed_query(text: str) -> list[float]:
    import asyncio

    return (await asyncio.to_thread(embed, [text]))[0]
