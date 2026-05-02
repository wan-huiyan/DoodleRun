"""Cat outline — doodle style.

Faces RIGHT. Signature features (in order of importance):
1. Two BIG pointy triangle ears on top of the head — exaggerated, ~2.5 units
   tall, much taller than realistic anatomy.
2. Long curving tail held UP HIGH, curling forward at the tip.
3. Arched back rising in the middle.
4. Slim body, small round head, two legs.

Cat reads as "cat" mostly because of ears + raised tail. Everything else is
just oval body.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

CAT_OUTLINE: List[Point] = [
    # Nose tip
    (11.0, 4.0),
    # Top of nose up to forehead
    (10.7, 4.6),
    (10.2, 5.1),

    # Big right ear (closer to snout) — tall pointy triangle
    (10.0, 5.2),
    (10.4, 8.0),     # ear 1 tip — TALL
    (9.4, 5.4),

    # Forehead between ears
    (9.0, 5.4),

    # Big left ear (rear) — tall pointy triangle
    (8.6, 5.4),
    (8.1, 8.0),      # ear 2 tip — TALL
    (7.6, 5.4),

    # Arched back: rises in the middle, then descends to rump
    (7.0, 5.7),
    (5.5, 6.4),      # arch peak
    (4.0, 6.0),
    (3.0, 5.6),

    # Tail rising HIGH from the rump, curling forward at the tip
    (2.6, 5.9),
    (1.9, 6.7),
    (1.4, 7.7),
    (1.5, 8.7),      # top of tail
    (2.3, 9.0),      # tail tip (curled forward)
    (2.9, 8.4),
    (2.7, 7.4),
    (3.1, 6.2),

    # Rump down to back leg
    (3.5, 4.6),
    (3.5, 2.4),

    # Back leg (slim)
    (3.5, 0.5),
    (3.5, 0.2),
    (4.7, 0.2),
    (4.7, 0.5),
    (4.6, 1.9),

    # Belly
    (6.2, 1.9),
    (8.0, 1.9),

    # Front leg (slim)
    (8.5, 2.0),
    (8.5, 0.5),
    (8.5, 0.2),
    (9.7, 0.2),
    (9.7, 0.5),
    (9.6, 1.9),

    # Chest, throat, close
    (10.1, 2.7),
    (10.5, 3.4),
    (11.0, 4.0),
]
