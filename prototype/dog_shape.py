"""Dog outline — doodle style.

Faces RIGHT. Designed by the "ONE signature feature" principle:
ONE big floppy EAR drooping forward from the back of the head — the cat-
vs-dog distinguisher. Side-profile convention shows one ear (the visible
one); two competing ear-loops just looked like duplicated front legs in
the v1 design.

Long horizontal body (beagle/dachshund stance), long rectangular snout,
tail held UP and slightly forward.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

DOG_OUTLINE: List[Point] = [
    # Snout tip
    (13.0, 3.5),
    # Top of long rectangular snout
    (13.0, 4.5),
    (12.0, 4.7),

    # Forehead up to top of head
    (11.5, 5.0),
    (11.0, 5.5),

    # ONE BIG FLOPPY EAR — drooping forward from the back of the head,
    # integrated into the head silhouette as a downward U-shape. Tip
    # ends at y=2.7, well clear of the front leg's x range.
    (10.5, 5.2),     # ear front, going down
    (9.8, 4.0),
    (9.5, 2.8),      # ear tip (drooped low)
    (10.2, 2.6),
    (10.5, 4.0),
    (10.7, 5.0),     # back to head

    # Top of head behind ear, then long top of back
    (10.5, 5.7),
    (8.5, 5.8),
    (6.0, 5.8),
    (3.5, 5.5),

    # Tail UP and slightly forward (wagging)
    (3.0, 5.7),
    (2.5, 6.6),
    (2.5, 7.6),      # tail tip
    (3.2, 7.6),
    (3.5, 6.6),
    (3.7, 5.5),

    # Rump down
    (4.0, 4.0),
    (4.0, 2.5),

    # Back leg (longer than cat — dog stance)
    (4.0, 0.4),
    (4.0, 0.2),
    (5.3, 0.2),
    (5.3, 0.4),
    (5.2, 2.0),

    # Belly (long body)
    (6.8, 1.8),
    (9.3, 1.8),

    # Front leg
    (9.8, 2.0),
    (9.8, 0.4),
    (9.8, 0.2),
    (11.2, 0.2),
    (11.2, 0.4),
    (11.0, 2.0),

    # Chest curving up under the snout
    (11.6, 2.5),
    (12.2, 3.0),
    (12.6, 3.3),
    (13.0, 3.5),
]
