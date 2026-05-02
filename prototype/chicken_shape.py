"""Chicken outline (standing, side profile, facing right).

Distinctive features: jagged comb on top of the head (3 little peaks), a
small triangular beak protruding forward, plump rounded body, layered tail
feathers (stepped triangle) at the back, two thin legs with feet. Wattle
under the beak gives the head a chicken silhouette.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

CHICKEN_OUTLINE: List[Point] = [
    # Beak: small forward triangle
    (11.5, 5.5),   # beak tip
    (10.7, 5.9),   # top of beak meeting forehead
    (10.5, 6.0),

    # Comb: three jagged peaks on top of the head
    (10.4, 6.6),
    (10.0, 7.0),   # comb peak 1
    (9.6, 6.5),
    (9.3, 7.1),    # comb peak 2 (tallest)
    (8.9, 6.5),
    (8.6, 6.8),    # comb peak 3
    (8.3, 6.4),

    # Back of head down to neck
    (8.0, 5.8),
    (7.6, 5.4),

    # Top of plump body (gentle arc up and over)
    (6.5, 5.5),
    (5.0, 5.7),
    (3.5, 5.5),

    # Tail feathers: stepped triangle pointing up-and-back
    (2.5, 5.7),
    (1.5, 6.5),    # outer feather tip 1
    (2.0, 5.5),
    (1.0, 6.0),    # outer feather tip 2
    (1.5, 5.0),
    (0.7, 5.2),    # outer feather tip 3 (back-most)
    (1.5, 4.5),

    # Rump and back of body curving down
    (2.5, 4.0),
    (3.0, 2.8),

    # Back leg (thin)
    (3.2, 1.5),
    (3.2, 0.5),    # ankle
    (3.0, 0.2),    # back of foot
    (4.2, 0.2),    # toe tip
    (4.0, 0.5),    # back to ankle (inner)
    (3.8, 1.5),

    # Belly between legs (round and full)
    (5.0, 2.2),
    (6.5, 2.5),
    (7.5, 2.4),

    # Front leg (thin)
    (8.0, 1.8),
    (8.0, 0.5),
    (7.8, 0.2),
    (9.0, 0.2),
    (8.8, 0.5),
    (8.6, 1.8),

    # Breast bulge curving up to throat
    (9.5, 2.8),
    (10.2, 3.8),
    (10.6, 4.5),

    # Wattle: small bump hanging below beak
    (10.4, 4.9),
    (10.7, 5.0),
    (10.6, 5.2),

    # Underside of beak back to start
    (10.9, 5.3),
    (11.5, 5.5),
]
