"""Shared helpers for animal-outline polylines.

Each shape file (pig_shape.py, cat_shape.py, …) just exports a list of
(x, y) waypoints in arbitrary "shape units"; the helpers here compute its
perimeter, resample to a target waypoint count, and return its bounding box
so the route generator can scale and project consistently.
"""

from __future__ import annotations

import math
from typing import List, Tuple

Point = Tuple[float, float]


def outline_perimeter(points: List[Point]) -> float:
    """Sum of Euclidean segment lengths along the polyline (shape units)."""
    return sum(
        math.hypot(x2 - x1, y2 - y1)
        for (x1, y1), (x2, y2) in zip(points, points[1:])
    )


def resample(points: List[Point], n: int) -> List[Point]:
    """Resample the polyline to exactly n points evenly spaced along its length.

    Endpoints are preserved. Used to keep OSRM waypoint counts predictable
    and below the demo server's per-request limit while preserving the
    overall shape silhouette.
    """
    if n < 2:
        raise ValueError("n must be >= 2")
    seg_lengths = [
        math.hypot(x2 - x1, y2 - y1)
        for (x1, y1), (x2, y2) in zip(points, points[1:])
    ]
    total = sum(seg_lengths)
    if total == 0:
        return [points[0]] * n

    step = total / (n - 1)
    out: List[Point] = [points[0]]
    seg_idx = 0
    seg_consumed = 0.0
    for i in range(1, n - 1):
        target = i * step
        while seg_idx < len(seg_lengths) and seg_consumed + seg_lengths[seg_idx] < target:
            seg_consumed += seg_lengths[seg_idx]
            seg_idx += 1
        if seg_idx >= len(seg_lengths):
            out.append(points[-1])
            continue
        remaining = target - seg_consumed
        frac = remaining / seg_lengths[seg_idx] if seg_lengths[seg_idx] > 0 else 0
        x1, y1 = points[seg_idx]
        x2, y2 = points[seg_idx + 1]
        out.append((x1 + frac * (x2 - x1), y1 + frac * (y2 - y1)))
    out.append(points[-1])
    return out


def bounding_box(points: List[Point]) -> Tuple[float, float, float, float]:
    """Return (min_x, min_y, max_x, max_y) of the polyline."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def compose_route(
    outline: List[Point],
    interior_features: List[List[Point]] | None = None,
) -> List[Point]:
    """Combine an outline polyline with interior-feature polylines into a single
    closed route a runner can trace in one pass.

    For each interior feature, the route detours from the outline anchor
    closest to the feature's first point, traces the feature, then jumps
    back to the same anchor before continuing along the outline. Interior
    features are anchored independently — order is determined by which
    anchor each feature is closest to, so multiple features attached to the
    same anchor stack in insertion order.

    This is generic — no animal-specific logic. Whether a feature is a
    whisker, nostril, eye, or any other thin stroke is irrelevant; the
    composer just needs (outline polyline, list of feature polylines).
    """
    if not interior_features:
        return list(outline)

    # Index features by closest outline anchor (index in `outline`).
    by_anchor: dict[int, List[List[Point]]] = {}
    for feat in interior_features:
        if not feat:
            continue
        first = feat[0]
        best_i = min(
            range(len(outline)),
            key=lambda i: (outline[i][0] - first[0]) ** 2 + (outline[i][1] - first[1]) ** 2,
        )
        by_anchor.setdefault(best_i, []).append(feat)

    out: List[Point] = []
    for i, anchor in enumerate(outline):
        out.append(anchor)
        if i in by_anchor:
            for feat in by_anchor[i]:
                # Trace feature: anchor → feature points → back to anchor
                out.extend(feat)
                out.append(anchor)
    return out
