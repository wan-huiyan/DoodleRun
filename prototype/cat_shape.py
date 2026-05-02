"""Cat outline — doodle style.

Faces RIGHT. Designed by the "ONE signature feature" principle:
two HUGE pointy triangle EARS dominate the silhouette — ~3 units tall,
roughly half the body height. Slim curving body, long graceful tail
rising from the rump and curling at the tip.

The pointy triangle ears are the primary cat-vs-dog distinguisher in
GPS art (Strava cats consistently use them oversized).
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

CAT_OUTLINE: List[Point] = [
    # Nose tip
    (10.0, 4.0),
    # Top of nose, forehead
    (9.7, 4.6),
    (9.3, 5.0),

    # HUGE pointy ear 1 (front) — ~3 units tall
    (9.0, 5.1),
    (9.5, 8.0),
    (8.5, 5.2),

    # Forehead between ears
    (8.2, 5.2),

    # HUGE pointy ear 2 (rear)
    (7.9, 5.2),
    (7.5, 8.0),
    (7.0, 5.2),

    # Slight arched back
    (6.0, 5.5),
    (4.5, 5.8),
    (3.0, 5.5),

    # Tail rising from rump and curling forward at the tip
    (2.5, 5.8),
    (1.9, 6.7),
    (1.4, 7.7),
    (1.5, 8.6),      # top
    (2.2, 8.9),      # tail tip (curled forward)
    (2.7, 8.3),
    (2.5, 7.3),
    (2.9, 6.0),

    # Rump down
    (3.3, 4.5),
    (3.3, 2.5),

    # Back leg (slim)
    (3.3, 0.4),
    (3.3, 0.2),
    (4.3, 0.2),
    (4.3, 0.4),
    (4.2, 2.0),

    # Belly
    (5.6, 2.0),
    (7.5, 2.0),

    # Front leg (slim)
    (8.0, 2.0),
    (8.0, 0.4),
    (8.0, 0.2),
    (9.0, 0.2),
    (9.0, 0.4),
    (8.9, 2.0),

    # Chest, throat, close
    (9.3, 2.7),
    (9.6, 3.4),
    (10.0, 4.0),
]
