"""Deterministic overlapping chunker. No model involved."""

from __future__ import annotations

from minuta.settings import get_settings


def chunk(text: str, *, target: int | None = None, overlap: int | None = None,
          maximum: int | None = None) -> list[str]:
    settings = get_settings()
    target = target or settings.chunk_target_chars
    overlap = overlap or settings.chunk_overlap_chars
    maximum = maximum or settings.chunk_max_chars
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, current = [], ""
    for para in paras:
        candidate = f"{current}\n{para}".strip() if current else para
        if len(candidate) > target and current:
            chunks.append(current[:maximum])
            current = current[-overlap:] + "\n" + para if overlap else para
        else:
            current = candidate
        while len(current) > maximum:
            chunks.append(current[:maximum])
            current = current[maximum - overlap:]
    if current.strip():
        chunks.append(current[:maximum])
    return [c for c in chunks if c.strip()]
