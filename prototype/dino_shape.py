"""Dinosaur outline — doodle style (brontosaurus + stegosaurus plates).

Faces RIGHT. Signature features (in order of importance):
1. Long curving NECK rising up to a small head at the top-right.
2. Three back PLATES (stegosaurus-style triangles) along the spine.
3. Long TAPERING TAIL trailing horizontally to the left.
4. Big rounded body, two thick legs.

Trace order: small head at top-right → down the back of the neck → over the
back (with three plates) → into the long tapering tail → underside of tail
→ up the chest → up the front of the neck → close at the head.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

DINO_OUTLINE: List[Point] = [
    # Head: small, top-right
    (16.0, 7.6),     # snout tip
    (16.0, 8.2),     # top of head
    (15.4, 8.4),     # back of head

    # Down BACK of long neck to top of body
    (14.5, 7.9),
    (13.5, 7.0),
    (12.5, 6.0),
    (11.5, 5.5),

    # Three back PLATES (stegosaurus triangles) along the spine
    (11.0, 5.5),
    (10.4, 6.7),     # plate 1
    (9.8, 5.5),
    (9.3, 5.5),
    (8.5, 7.4),      # plate 2 (tallest — middle)
    (7.7, 5.5),
    (7.2, 5.5),
    (6.6, 6.7),      # plate 3
    (6.0, 5.5),

    # Top of back curving down toward tail
    (5.0, 5.3),
    (4.0, 5.0),

    # Long tapering tail (top side)
    (3.0, 4.7),
    (2.0, 4.5),
    (1.0, 4.3),
    (0.2, 4.1),      # tail tip

    # Tail tip underside (taper)
    (0.2, 3.7),

    # Tail underside back toward rump
    (1.0, 3.7),
    (2.0, 3.8),
    (3.0, 3.7),
    (4.0, 3.5),

    # Rump down to back leg
    (4.5, 3.0),
    (5.0, 2.5),

    # Back leg (thick)
    (5.0, 0.5),
    (5.0, 0.2),
    (6.6, 0.2),
    (6.6, 0.5),
    (6.4, 2.2),

    # Belly (between legs)
    (7.6, 2.2),
    (9.0, 2.2),
    (10.5, 2.2),

    # Front leg (thick)
    (11.0, 2.2),
    (11.0, 0.5),
    (11.0, 0.2),
    (12.6, 0.2),
    (12.6, 0.5),
    (12.4, 2.5),

    # Chest curving up to base of neck
    (12.8, 3.5),
    (13.2, 4.5),

    # Up FRONT of long neck to chin
    (13.7, 5.5),
    (14.2, 6.5),
    (14.8, 7.3),
    (15.4, 7.7),
    (15.7, 7.6),     # under chin

    # Underside of mouth back to snout tip
    (16.0, 7.6),
]
