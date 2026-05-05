"""Dinosaur outline — doodle style (brontosaurus + stegosaurus plates).

Faces RIGHT. Designed by the "ONE signature feature" principle:
the LONG NECK rising up to a small head at the very top — the iconic
brontosaurus silhouette. Three back plates add accent (stegosaurus mash-
up keeps the spine visually busy at the right scale).

Trace order: small head at top-right → down the back of the long neck →
along the back through three plates → into the long tapering tail →
underside of tail → up the chest → up the front of the long neck → close.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

DINO_OUTLINE: List[Point] = [
    # Small head perched at the top
    (15.5, 9.0),     # snout tip
    (15.5, 9.5),     # top of head
    (14.8, 9.5),     # back of head

    # Down the BACK of the long neck (exaggerated height)
    (14.0, 8.7),
    (13.0, 7.7),
    (12.0, 6.5),
    (11.0, 5.5),

    # Three back plates along the spine
    (10.5, 5.5),
    (10.0, 6.7),     # plate 1
    (9.5, 5.5),
    (9.0, 5.5),
    (8.5, 7.4),      # plate 2 (tallest)
    (8.0, 5.5),
    (7.5, 5.5),
    (7.0, 6.7),      # plate 3
    (6.5, 5.5),

    # Top of back curving down to tail
    (5.0, 5.3),
    (4.0, 5.0),

    # Long tapering tail (top side)
    (3.0, 4.7),
    (2.0, 4.5),
    (1.0, 4.3),
    (0.2, 4.1),      # tail tip top
    (0.2, 3.7),      # tail tip bottom (taper)

    # Tail underside back to rump
    (1.0, 3.7),
    (2.0, 3.8),
    (3.0, 3.7),
    (4.0, 3.5),

    # Rump down to back leg
    (4.5, 3.0),
    (5.0, 2.5),

    # Back leg (thick)
    (5.0, 0.4),
    (5.0, 0.2),
    (6.6, 0.2),
    (6.6, 0.4),
    (6.4, 2.2),

    # Belly
    (7.6, 2.2),
    (9.0, 2.2),
    (10.5, 2.2),

    # Front leg (thick)
    (11.0, 2.2),
    (11.0, 0.4),
    (11.0, 0.2),
    (12.6, 0.2),
    (12.6, 0.4),
    (12.4, 2.5),

    # Chest curving up to base of neck
    (12.8, 3.5),
    (13.2, 4.5),

    # Up the FRONT of the long neck to chin
    (13.7, 5.5),
    (14.2, 6.7),
    (14.8, 7.8),
    (15.3, 8.7),
    (15.5, 9.0),
]
