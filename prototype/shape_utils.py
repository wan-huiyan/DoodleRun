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


def simplify_vw(points: List[Point], target_count: int) -> List[Point]:
    """Visvalingam-Whyatt simplification down to ~``target_count`` vertices.

    Wraps ``simplification.cutil.simplify_coords_vwp`` (the Rust-backed
    "preserve" variant — never returns fewer than 3 points). VW removes
    the smallest-triangle vertex first and is perceptually superior to
    RDP for rounded animal silhouettes (preserves area, not deviation).

    The library uses an absolute area threshold; we binary-search the
    threshold so the output lands at the requested vertex count
    (±10%). For the small inputs used here (50–500 input points),
    each VW call is microseconds — the search is essentially free.
    """
    if len(points) <= target_count:
        return list(points)
    if target_count < 3:
        raise ValueError("target_count must be >= 3")

    # Lazy import so users without the lib can still use the rest of
    # shape_utils.
    from simplification.cutil import simplify_coords_vw

    # Estimate a threshold range from the polyline scale.
    min_x, min_y, max_x, max_y = bounding_box(points)
    span = max(max_x - min_x, max_y - min_y, 1e-9)
    lo, hi = (span ** 2) * 1e-9, (span ** 2)
    coords = [list(p) for p in points]
    best = points
    for _ in range(40):
        mid = math.sqrt(lo * hi)
        out = simplify_coords_vw(coords, mid)
        if len(out) > target_count:
            lo = mid                # threshold too low, drop more points
        elif len(out) < target_count:
            hi = mid                # threshold too high, keep more points
        else:
            return [(p[0], p[1]) for p in out]
        # Track the closest result we've seen (within ±10%).
        if abs(len(out) - target_count) <= max(1, target_count // 10):
            best = [(p[0], p[1]) for p in out]
        if hi / lo < 1.01:
            break
    return best
