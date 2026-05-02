"""Pig outline as ordered (x, y) waypoints for a single continuous tracing path.

Coordinates are in arbitrary units; the pig faces right with snout near x=11.5,
tail at x≈1, ground at y≈0.1, top of head/ear at y≈5.6. The path starts at the
snout tip, traces clockwise around head→back→tail→belly→legs→chin, and closes.
"""

from __future__ import annotations

import math
from typing import List, Tuple

Point = Tuple[float, float]

PIG_OUTLINE: List[Point] = [
    # Snout tip and top of snout
    (11.5, 3.0),
    (11.5, 3.6),
    (10.7, 3.8),

    # Forehead and ear
    (10.0, 4.2),
    (9.0, 4.5),
    (8.7, 5.3),   # ear back
    (9.4, 5.6),   # ear tip
    (9.7, 4.7),   # ear front

    # Top of back to tail base
    (8.0, 4.6),
    (6.0, 4.7),
    (4.0, 4.6),
    (2.5, 4.4),

    # Curly tail
    (1.7, 4.6),
    (1.2, 5.0),
    (0.7, 4.8),
    (0.7, 4.3),
    (1.2, 4.1),
    (1.5, 4.4),

    # Rump down to back legs
    (1.5, 3.5),
    (1.6, 2.5),

    # Left back leg (down + foot + up)
    (1.7, 1.5),
    (1.5, 0.5),
    (1.5, 0.1),
    (2.2, 0.1),
    (2.2, 1.4),

    # Belly between back legs
    (3.0, 1.6),

    # Right back leg
    (3.5, 1.4),
    (3.5, 0.1),
    (4.2, 0.1),
    (4.2, 1.5),

    # Belly to front legs
    (5.5, 1.7),
    (6.5, 1.7),

    # Left front leg
    (7.0, 1.5),
    (7.0, 0.1),
    (7.7, 0.1),
    (7.7, 1.5),

    # Belly between front legs
    (8.3, 1.7),

    # Right front leg
    (8.8, 1.5),
    (8.8, 0.1),
    (9.5, 0.1),
    (9.5, 1.6),

    # Chest up to chin
    (10.0, 2.2),
    (10.5, 2.6),
    (11.0, 2.7),
    (11.5, 2.8),

    # Close loop to snout tip
    (11.5, 3.0),
]


def outline_perimeter(points: List[Point]) -> float:
    """Sum of Euclidean segment lengths along the outline (in shape units)."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def resample(points: List[Point], n: int) -> List[Point]:
    """Resample the polyline to exactly n points evenly spaced along its length.

    The first and last points of the input are preserved. Useful for keeping
    OSRM waypoint counts under demo-server limits while preserving shape.
    """
    if n < 2:
        raise ValueError("n must be >= 2")
    seg_lengths = [math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(points, points[1:])]
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
    """Return (min_x, min_y, max_x, max_y) of the outline."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)
