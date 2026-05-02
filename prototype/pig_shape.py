"""Pig outline — doodle style.

Faces RIGHT. Signature features (in order of importance):
1. Curly spiral tail rising up from the rump — the silhouette that screams
   "pig". Drawn as a self-intersecting spiral (~1.5 turns) — visible as a
   crossing-line curl when rendered as a polyline (the way a runner traces
   it on the map).
2. Round snout sticking out at the front.
3. Two small pointy ears on top of the head.
4. Big oval body, two stubby legs.

Drawn as a single closed polyline. Traced clockwise starting at the snout
tip. The tail spiral coils OUT, AROUND, then INWARD, then exits back to
the body — the in-and-out is the whole point of "curly".

Coordinate system: x grows right, y grows up.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

PIG_OUTLINE: List[Point] = [
    # Snout tip
    (14.0, 4.0),
    # Top of snout up to forehead
    (13.8, 4.8),
    (13.2, 5.2),

    # Ear 1 (front, closer to snout) — pointy triangle
    (12.6, 5.4),
    (12.5, 7.2),     # ear 1 tip
    (11.7, 5.4),

    # Across the brow
    (11.2, 5.4),

    # Ear 2 (rear) — pointy triangle
    (10.8, 5.4),
    (10.7, 7.2),     # ear 2 tip
    (10.0, 5.4),

    # Top of back: smooth arc from head to where the tail rises
    (8.5, 5.7),
    (6.5, 6.0),
    (4.5, 5.9),
    (3.2, 5.6),

    # ---- Curly spiral tail ------------------------------------------------
    # Stem rising from the back, then 1.5 turns of an outward-then-inward
    # spiral. Self-intersecting on purpose: when traced as a line on a map,
    # the crossings ARE the curl.
    (3.0, 6.5),      # stem rises
    (3.0, 7.2),      # top of stem
    (2.2, 7.6),      # outer spiral — top
    (1.0, 7.3),      # outer spiral — left
    (0.4, 6.4),      # outer spiral — bottom-left
    (0.7, 5.5),      # outer spiral — bottom
    (1.7, 5.3),      # outer spiral — bottom-right (closes outer loop)
    (2.5, 6.0),      # second turn — going up inside the outer loop
    (2.0, 6.7),      # second turn — top inside
    (1.2, 6.4),      # second turn — left inside
    (1.5, 5.8),      # innermost
    # Exit the spiral back toward the body
    (2.6, 5.5),

    # Rump down to back leg
    (2.7, 4.0),
    (2.8, 2.4),

    # Back leg (stubby, wide foot)
    (2.8, 0.6),
    (2.8, 0.2),
    (4.6, 0.2),
    (4.6, 0.6),
    (4.4, 1.8),

    # Belly
    (6.2, 1.6),
    (8.4, 1.6),
    (10.5, 1.7),

    # Front leg (stubby)
    (11.0, 2.0),
    (11.2, 0.6),
    (11.2, 0.2),
    (13.0, 0.2),
    (13.0, 0.6),
    (12.8, 2.2),

    # Chest curving up to underside of snout
    (13.3, 2.9),
    (13.7, 3.5),
    (14.0, 4.0),
]
