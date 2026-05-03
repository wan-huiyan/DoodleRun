"""Load and curate Quick Draw sketches as closed polylines.

Quick Draw simplified .ndjson rows look like:
    {"key_id": "...", "word": "pig", "recognized": true,
     "drawing": [[[xs], [ys]], [[xs], [ys]], ...], ...}
Each stroke is two equal-length lists of int coords in a 0-255 box,
y-axis pointing DOWN. Coordinates are RDP-simplified at epsilon=2.0.

We collapse multi-stroke drawings into a single closed polyline by
chaining strokes head-to-tail, then closing the loop. Templates with
too many strokes or aspect-ratio extremes are filtered out — they
rarely render as recognizable animals at street scale.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple


@dataclass
class Template:
    """A normalized doodle template, ready to be projected onto a map."""
    word: str
    key_id: str
    n_strokes: int
    # closed polyline in centered, unit-scaled coords (y flipped to point UP)
    # x in [-0.5, 0.5], y in [-0.5, 0.5], last point == first point
    coords: List[Tuple[float, float]]


def _drawing_to_polyline(drawing) -> List[Tuple[float, float]]:
    """Concatenate strokes into a single ordered polyline."""
    pts: List[Tuple[float, float]] = []
    for stroke in drawing:
        xs, ys = stroke[0], stroke[1]
        for x, y in zip(xs, ys):
            pts.append((float(x), float(y)))
    return pts


def _normalize(pts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Center, scale to unit box, flip y so up is positive, close the loop."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    w = maxx - minx
    h = maxy - miny
    span = max(w, h)
    if span == 0:
        return []
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2
    out = [((x - cx) / span, -(y - cy) / span) for x, y in pts]
    if out[0] != out[-1]:
        out.append(out[0])
    return out


def _polyline_length(pts: List[Tuple[float, float]]) -> float:
    return sum(
        math.hypot(b[0] - a[0], b[1] - a[1])
        for a, b in zip(pts, pts[1:])
    )


def _aspect_ratio(pts: List[Tuple[float, float]]) -> float:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    if h == 0:
        return float('inf')
    return w / h


def iter_templates(
    ndjson_path: Path,
    *,
    word: str | None = None,
    max_count: int = 50_000,
    require_recognized: bool = True,
    max_strokes: int = 6,
    min_points: int = 12,
    max_points: int = 200,
    min_aspect: float = 0.4,
    max_aspect: float = 3.0,
) -> Iterable[Template]:
    """Yield normalized templates from a Quick Draw .ndjson file.

    Filters: recognized=True, stroke count within bounds, point count
    within bounds, aspect ratio not too extreme. These together knock
    out the worst scribbles and the 'just a face' minimalist sketches.
    """
    with open(ndjson_path) as f:
        for line in f:
            row = json.loads(line)
            if max_count <= 0:
                break
            if require_recognized and not row.get('recognized'):
                continue
            if word and row.get('word') != word:
                continue
            if len(row['drawing']) > max_strokes:
                continue
            poly = _drawing_to_polyline(row['drawing'])
            if not (min_points <= len(poly) <= max_points):
                continue
            ar = _aspect_ratio(poly)
            if not (min_aspect <= ar <= max_aspect):
                continue
            normed = _normalize(poly)
            if len(normed) < min_points:
                continue
            yield Template(
                word=row['word'],
                key_id=row['key_id'],
                n_strokes=len(row['drawing']),
                coords=normed,
            )
            max_count -= 1


def load_top_templates(
    ndjson_path: Path,
    n: int = 50,
    **kwargs,
) -> List[Template]:
    """Load up to n templates, ranked by 'cleanness' (1 stroke > more).

    The top 5x candidates by perimeter are pulled, then the lowest-stroke
    samples kept. Single-stroke drawings are usually closed loops drawn
    in one go and produce the clearest GPS art.
    """
    pool = list(iter_templates(ndjson_path, max_count=5 * n, **kwargs))
    pool.sort(key=lambda t: (t.n_strokes, -_polyline_length(t.coords)))
    return pool[:n]


if __name__ == '__main__':
    import sys
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('data/quickdraw/pig.ndjson')
    templates = load_top_templates(path, n=10)
    print(f'loaded {len(templates)} templates from {path.name}')
    for t in templates[:5]:
        print(f'  {t.word} {t.key_id} strokes={t.n_strokes} pts={len(t.coords)}')
