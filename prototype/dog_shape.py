"""Dog outline (standing, side profile, facing right).

Distinctive features: pronounced rectangular snout, long floppy ear hanging
DOWN from the back of the head, wagging tail held UP and forward. Two
visible legs. Dog body is longer and lower than cat/pig — beagle-ish.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

DOG_OUTLINE: List[Point] = [
    # Snout tip
    (13.5, 3.2),
    (13.5, 4.2),
    (12.0, 4.4),   # top of snout meets head

    # Forehead and crown
    (11.5, 5.1),
    (10.5, 5.3),

    # Floppy ear: hangs down behind head, then back up to skull
    (10.0, 5.2),
    (9.6, 4.5),    # ear flap going down
    (9.4, 3.2),    # ear tip (low)
    (9.9, 3.0),    # ear bottom (curls)
    (10.2, 4.0),   # back side of ear
    (10.4, 4.8),   # back to head

    # Top of back from head to tail
    (9.5, 5.0),
    (7.5, 5.1),
    (5.5, 5.0),
    (3.5, 4.9),

    # Tail base, tail held up and forward
    (2.8, 5.0),
    (2.3, 5.6),
    (2.0, 6.5),
    (2.6, 6.8),    # tail tip
    (3.0, 6.0),
    (3.2, 5.2),

    # Rump down
    (3.5, 4.0),
    (3.7, 2.5),

    # Back leg
    (3.7, 1.2),
    (3.7, 0.2),
    (5.2, 0.2),
    (5.2, 1.5),

    # Belly (long body)
    (7.0, 1.7),
    (9.5, 1.7),

    # Front leg
    (10.0, 1.5),
    (10.0, 0.2),
    (11.5, 0.2),
    (11.5, 1.7),

    # Chest, underside of snout, close
    (12.0, 2.3),
    (12.5, 2.8),
    (13.0, 3.0),
    (13.5, 3.2),
]
