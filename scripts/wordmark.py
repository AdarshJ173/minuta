#!/usr/bin/env python3
"""Generate the Minuta dot-matrix wordmark (assets/minuta.svg).

Grid math only — no fonts involved, so it renders identically everywhere.
Re-run after editing GLYPHS; commit the SVG.
"""
from pathlib import Path

GLYPHS = {
    "M": ["X...X", "XX.XX", "X.X.X", "X...X", "X...X", "X...X", "X...X"],
    "I": ["XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "XXXXX"],
    "N": ["X...X", "XX..X", "XX..X", "X.X.X", "X..XX", "X..XX", "X...X"],
    "U": ["X...X", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."],
    "T": ["XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "..X.."],
    "A": ["..X..", ".X.X.", "X...X", "X...X", "XXXXX", "X...X", "X...X"],
}

WORD = "MINUTA"
PITCH = 26
R = 8
GAP_COLS = 2
LIT = "#f5f5f7"
DIM = "#232326"
PAD = 26


def main() -> None:
    rows = len(next(iter(GLYPHS.values())))
    total_cols = 6 * 5 + GAP_COLS * (len(WORD) - 1)
    w, h = total_cols * PITCH + PAD * 2, rows * PITCH + PAD * 2
    # Full dotted field: every grid position gets a dim dot,
    # glyph cells marked X get a lit one (omnigraph-style backdrop).
    lit_cells = set()
    col = 0
    for ch in WORD:
        for r, row in enumerate(GLYPHS[ch]):
            for c, cell in enumerate(row):
                if cell == "X":
                    lit_cells.add((col + c, r))
        col += 5 + GAP_COLS
    total_cols = col - GAP_COLS
    w, h = total_cols * PITCH + PAD * 2, rows * PITCH + PAD * 2
    circles = []
    for r in range(rows):
        for c in range(total_cols):
            cx, cy = PAD + c * PITCH + PITCH // 2, PAD + r * PITCH + PITCH // 2
            fill = LIT if (c, r) in lit_cells else DIM
            circles.append(f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="{fill}"/>')
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="MINUTA">\n<title>MINUTA</title>\n'
        + "\n".join(circles)
        + "\n</svg>\n"
    )
    out = Path(__file__).resolve().parents[1] / "assets" / "minuta.svg"
    out.parent.mkdir(exist_ok=True)
    out.write_text(svg)
    print(f"wrote {out} ({w}x{h}, {len(circles)} dots)")


if __name__ == "__main__":
    main()
