"""Load and curate Quick Draw sketches as outline-only closed polylines.

Quick Draw simplified .ndjson rows look like:
    {"key_id": "...", "word": "pig", "recognized": true,
     "drawing": [[[xs], [ys]], [[xs], [ys]], ...], ...}
Each stroke is two equal-length lists of int coords in a 0-255 box,
y-axis pointing DOWN. Coordinates are RDP-simplified at epsilon=2.0.

GPS art needs a SINGLE continuous outline. Quick Draw drawings often
include interior detail strokes (eyes, nostrils, spots, mouths) that
ruin the silhouette when treated as a path. We extract only the OUTER
OUTLINE plus any strokes that meaningfully extend it (tail, ear, trunk):

  1. Sort strokes by perimeter; the longest is the main outline.
  2. For every other stroke, decide interior vs extension by checking
     what fraction of its length falls inside the main outline's
     buffered convex hull.
  3. Discard interior strokes (>= INTERIOR_THRESHOLD inside).
  4. Splice extension strokes into the main outline at the nearest
     endpoint pair, then close the loop.

A template is only useful for GPS art if its CLEANED outline still
covers the silhouette — short or near-trivial main strokes are dropped.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

from shapely.geometry import LineString, MultiPoint, Point


# A stroke whose length is at least this fraction inside the main
# outline's hull is treated as interior detail (eye, nostril, spot)
# and discarded.
INTERIOR_THRESHOLD = 0.7

# Buffer applied to the main outline's convex hull when classifying
# other strokes. In normalized 0-255 Quick Draw units; small values
# tighten the "interior" definition. 6 ≈ 2.5 % of canvas width.
HULL_BUFFER_PX = 6.0


Stroke = List[Tuple[float, float]]


@dataclass
class Template:
    """A normalized outline-only doodle template."""
    word: str
    key_id: str
    n_strokes: int  # original stroke count (before filtering)
    n_kept_strokes: int  # main + extensions kept
    n_discarded_strokes: int
    coords: List[Tuple[float, float]]  # closed, normalized to [-0.5, 0.5]


def _stroke_to_pts(stroke) -> Stroke:
    xs, ys = stroke[0], stroke[1]
    return [(float(x), float(y)) for x, y in zip(xs, ys)]


def _polyline_length(pts: Stroke) -> float:
    return sum(
        math.hypot(b[0] - a[0], b[1] - a[1])
        for a, b in zip(pts, pts[1:])
    )


def _outline_only(strokes: List[Stroke]) -> Tuple[Stroke, int]:
    """Return (cleaned outline polyline, n_extensions_kept).

    Drops interior detail strokes; splices remaining extension strokes
    into the main outline at the nearest-endpoint pair.
    """
    if not strokes:
        return ([], 0)
    # Sort by perimeter, descending. Filter out trivially-short strokes.
    ranked = sorted(
        ((s, _polyline_length(s)) for s in strokes if len(s) >= 2),
        key=lambda x: -x[1],
    )
    if not ranked:
        return ([], 0)
    main = list(ranked[0][0])
    if len(main) < 4:
        return (main, 0)

    # Build the "is this point interior?" classifier from the main hull.
    main_hull = MultiPoint(main).convex_hull.buffer(HULL_BUFFER_PX)

    def fraction_inside(pts: Stroke) -> float:
        if len(pts) < 2:
            return 1.0
        ls = LineString(pts)
        inside = ls.intersection(main_hull).length
        return inside / max(ls.length, 1e-9)

    extensions: List[Stroke] = []
    for s, _ in ranked[1:]:
        f_in = fraction_inside(s)
        if f_in < INTERIOR_THRESHOLD:
            extensions.append(s)
        # else: interior detail — drop silently.

    # Splice each extension into the main polyline at its nearest endpoint
    # pair. After splicing, the polyline goes: main -> extension -> main,
    # which when closed produces a loop around the body + appendage.
    # We accept that the splice may add a short bridging segment.
    polyline = list(main)
    for ext in extensions:
        # Try ext and ext-reversed; take whichever endpoint is nearest
        # to *some* main endpoint.
        candidates = [ext, list(reversed(ext))]
        best = None
        best_d = float('inf')
        for cand in candidates:
            for ins_idx, anchor in enumerate(polyline):
                d = math.hypot(cand[0][0] - anchor[0], cand[0][1] - anchor[1])
                if d < best_d:
                    best_d = d
                    best = (cand, ins_idx)
        if best is None:
            continue
        cand, ins_idx = best
        # Splice as a "spike": main[:ins_idx+1] -> ext -> ext_rev -> main[ins_idx+1:]
        polyline = polyline[: ins_idx + 1] + cand + list(reversed(cand)) + polyline[ins_idx + 1 :]

    return (polyline, len(extensions))


def _normalize(pts: Stroke) -> Stroke:
    """Center, scale to unit box, flip y so up is positive, close the loop."""
    if len(pts) < 3:
        return []
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    span = max(maxx - minx, maxy - miny)
    if span == 0:
        return []
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2
    out = [((x - cx) / span, -(y - cy) / span) for x, y in pts]
    if out[0] != out[-1]:
        out.append(out[0])
    return out


def _aspect_ratio(pts: Stroke) -> float:
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
    max_strokes: int = 8,
    min_main_points: int = 12,
    max_total_points: int = 220,
    min_aspect: float = 0.4,
    max_aspect: float = 3.0,
    min_main_perimeter_px: float = 200.0,
) -> Iterable[Template]:
    """Yield outline-only templates after filtering interior strokes.

    Filters: recognized=True, original stroke count <= max_strokes (loose
    upper bound — many will collapse to 1-2 after interior-stroke removal),
    main outline must be substantial (length and point count), aspect ratio
    not extreme. Eye/nostril/spot strokes are dropped automatically.
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
            n_strokes_orig = len(row['drawing'])
            if n_strokes_orig > max_strokes:
                continue
            strokes = [_stroke_to_pts(s) for s in row['drawing']]
            cleaned, n_kept_ext = _outline_only(strokes)
            if not cleaned or len(cleaned) < min_main_points:
                continue
            # the longest pre-cleaning stroke determines whether the
            # silhouette is substantial enough to be recognizable
            main_len = max(_polyline_length(s) for s in strokes)
            if main_len < min_main_perimeter_px:
                continue
            if len(cleaned) > max_total_points:
                continue
            ar = _aspect_ratio(cleaned)
            if not (min_aspect <= ar <= max_aspect):
                continue
            normed = _normalize(cleaned)
            if len(normed) < min_main_points:
                continue
            yield Template(
                word=row['word'],
                key_id=row['key_id'],
                n_strokes=n_strokes_orig,
                n_kept_strokes=1 + n_kept_ext,
                n_discarded_strokes=n_strokes_orig - (1 + n_kept_ext),
                coords=normed,
            )
            max_count -= 1


def load_top_templates(
    ndjson_path: Path,
    n: int = 50,
    **kwargs,
) -> List[Template]:
    """Load up to n outline-only templates.

    Ranks by (cleanness, simplicity):
      - prefer 1 kept stroke (main only) over splices
      - among equals, prefer fewer discarded interior strokes
        (those tend to have been less detailed source drawings)
      - tiebreak by longer main outline (more substantive silhouette)
    """
    pool = list(iter_templates(ndjson_path, max_count=8 * n, **kwargs))
    pool.sort(key=lambda t: (
        t.n_kept_strokes,
        t.n_discarded_strokes,
        -len(t.coords),
    ))
    return pool[:n]


if __name__ == '__main__':
    import sys
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('data/quickdraw/pig.ndjson')
    templates = load_top_templates(path, n=10)
    print(f'loaded {len(templates)} outline-only templates from {path.name}')
    for t in templates[:5]:
        print(f'  {t.word} {t.key_id} orig_strokes={t.n_strokes} '
              f'kept={t.n_kept_strokes} discarded={t.n_discarded_strokes} '
              f'pts={len(t.coords)}')
