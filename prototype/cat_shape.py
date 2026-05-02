"""Cat outline (standing, side profile, facing right).

Distinctive features: two pointed triangle ears on top of head, long curving
tail rising from the rump. Two visible legs (side profile). Cat is sleeker
and slightly shorter than the pig — body height is ~50% of pig's snout.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

CAT_OUTLINE: List[Point] = [
    # Nose tip and top of nose
    (12.0, 4.2),
    (11.8, 4.6),
    (11.3, 4.9),

    # Forehead between ears
    (10.7, 5.2),

    # Right ear (closer to snout)
    (10.5, 5.4),
    (10.9, 6.4),   # right ear tip
    (10.1, 5.5),

    # Left ear (closer to back)
    (9.8, 5.5),
    (9.6, 6.5),    # left ear tip
    (9.2, 5.4),

    # Top of head, neck, top of back
    (8.5, 5.2),
    (7.0, 5.5),
    (5.0, 5.6),
    (3.5, 5.5),
    (2.5, 5.4),

    # Tail base, tail rising and curling forward over back
    (1.8, 5.6),
    (1.2, 6.2),    # tail rising
    (1.0, 7.2),
    (1.5, 7.8),    # tail tip (curled forward)
    (2.2, 7.4),
    (2.0, 6.6),
    (2.5, 5.8),

    # Rump down
    (3.0, 4.5),
    (3.0, 3.0),

    # Back leg
    (3.0, 1.5),
    (3.0, 0.2),    # foot bottom outer
    (4.5, 0.2),    # foot bottom inner
    (4.5, 1.8),    # leg inner top

    # Belly
    (6.0, 2.0),
    (8.5, 2.0),

    # Front leg
    (9.0, 1.8),
    (9.0, 0.2),    # foot bottom outer
    (10.3, 0.2),   # foot bottom inner
    (10.3, 1.8),

    # Chest, throat, close
    (10.8, 2.5),
    (11.3, 3.3),
    (11.7, 3.8),
    (12.0, 4.2),
]
