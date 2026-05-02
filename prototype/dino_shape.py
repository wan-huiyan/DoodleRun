"""T-Rex / dinosaur outline (side profile, facing right).

Distinctive features: long horizontal body, three triangular spikes along
the back, very long tail trailing behind, small head, two large back legs
(no arms — kept simple for street-routing readability).
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

DINO_OUTLINE: List[Point] = [
    # Snout tip and top of head
    (15.0, 5.0),
    (15.0, 5.8),
    (14.0, 6.0),

    # Top of head down to start of back
    (13.0, 5.7),
    (12.5, 5.8),

    # Three back spikes (alternating up/down)
    (12.0, 5.7),
    (11.5, 6.6),   # spike 1 tip
    (11.0, 5.7),
    (10.0, 5.7),
    (9.5, 6.7),    # spike 2 tip (taller, middle)
    (9.0, 5.7),
    (8.0, 5.7),
    (7.5, 6.4),    # spike 3 tip
    (7.0, 5.6),

    # Back curves down toward tail
    (6.0, 5.4),
    (5.0, 5.0),
    (4.0, 4.5),

    # Long tapering tail (top side)
    (3.0, 4.0),
    (2.0, 3.5),
    (1.0, 3.2),
    (0.3, 3.0),    # tail tip
    (0.3, 2.5),    # tail tip underside
    (1.0, 2.5),
    (2.0, 2.7),
    (3.0, 2.8),
    (4.0, 3.2),

    # Rump down to leg
    (5.0, 3.5),
    (5.5, 3.0),

    # Big back leg with thigh + foot
    (5.5, 1.5),
    (5.5, 0.2),    # foot bottom heel
    (7.5, 0.2),    # foot bottom toe
    (7.5, 1.8),    # leg inner top

    # Underbelly between legs (short — T-Rex stance)
    (8.5, 2.0),
    (10.0, 2.0),

    # Second leg (the front-of-stance one)
    (10.5, 1.8),
    (10.5, 0.2),
    (12.5, 0.2),
    (12.5, 1.8),

    # Belly forward, chest, throat
    (13.0, 2.5),
    (13.5, 3.5),
    (14.0, 4.3),
    (14.5, 4.7),
    (15.0, 5.0),
]
