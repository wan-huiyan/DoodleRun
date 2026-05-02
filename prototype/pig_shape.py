"""Pig outline — doodle style.

Faces RIGHT. Designed by the "ONE signature feature" principle:
the CURLY SPIRAL TAIL is exaggerated to dominate the silhouette. Body is
a simple oval, snout is a small bump, two pointy ears.

Trace order (clockwise from snout): snout → ears → top of back → spiral
tail → rump → back leg → belly → front leg → chest → close.

The tail is a self-intersecting 1.25-turn open spiral. When traced as a
polyline on a map, the line crossings ARE the curl — the same trick a
cartoonist uses to draw a spiral with a single stroke.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

PIG_OUTLINE: List[Point] = [
    # Snout tip
    (13.0, 4.0),
    # Top of round snout up to forehead
    (13.0, 4.8),
    (12.0, 5.2),

    # Ear 1 (front) — pointy triangle
    (11.5, 5.4),
    (11.5, 7.0),
    (10.7, 5.4),

    # Across the brow
    (10.2, 5.4),

    # Ear 2 (rear) — pointy triangle
    (9.7, 5.4),
    (9.7, 7.0),
    (9.0, 5.4),

    # Top of back — gentle arc
    (7.0, 5.7),
    (5.0, 5.8),
    (3.0, 5.6),

    # ---- CURLY SPIRAL TAIL (the signature) -------------------------------
    # 1.25-turn open spiral, going UP-LEFT then back inward through itself.
    # The line crossings render as a clear curl.
    (2.7, 6.4),      # stem rises off the back
    (2.0, 7.2),      # outer top-right
    (0.7, 7.2),      # outer top
    (-0.2, 6.0),     # outer left
    (0.3, 4.7),      # outer bottom
    (1.6, 4.4),      # outer bottom-right
    (2.5, 5.1),      # closes outer loop, inside the curl
    (1.9, 5.7),      # second turn — going UP inside the loop
    (1.3, 5.5),      # innermost point of curl
    (2.3, 5.3),      # exit toward body

    # Rump down to back leg
    (2.7, 4.0),
    (2.8, 2.4),

    # Back leg (stubby out-and-back peninsula)
    (2.8, 0.4),
    (2.8, 0.2),
    (4.5, 0.2),
    (4.5, 0.4),
    (4.4, 1.8),

    # Belly
    (6.2, 1.7),
    (8.5, 1.7),
    (10.0, 1.8),

    # Front leg (stubby)
    (10.5, 0.4),
    (10.5, 0.2),
    (12.0, 0.2),
    (12.0, 0.4),
    (11.9, 2.0),

    # Chest curving up to underside of snout
    (12.4, 2.7),
    (12.7, 3.4),
    (13.0, 4.0),
]
