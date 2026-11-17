"""Deterministic chunker tests: overlap, bounds, empties."""

from minuta.chunks import chunk


def test_short_text_is_one_chunk():
    assert chunk("hello world", target=2600) == ["hello world"]


def test_long_text_splits_with_overlap():
    paras = [f"paragraph {i} " + ("word " * 200) for i in range(6)]
    out = chunk("\n".join(paras), target=500, overlap=50, maximum=800)
    assert len(out) > 1
    assert all(len(c) <= 800 for c in out)
    assert all(c.strip() for c in out)


def test_empty_lines_ignored():
    assert chunk("\n\n  \nhello\n\n") == ["hello"]
