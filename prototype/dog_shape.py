"""Dog outline — doodle style.

Faces RIGHT. Signature features (in order of importance):
1. Two FLOPPY ears that droop DOWN past the chin — the key contrast against
   the cat's pointy upward ears.
2. Long rectangular snout.
3. Tail held UP and slightly forward (wagging).
4. Longer, lower body than cat/pig (beagle-ish).

The floppy ears are drawn as long vertical loops protruding downward from
the top of the head — they end up well below the eye line, which is what
makes them read as floppy rather than pointy.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

DOG_OUTLINE: List[Point] = [
    # Snout tip
    (13.5, 3.5),
    # Top of long snout
    (13.5, 4.6),
    (12.6, 4.7),

    # Forehead up to top of head
    (12.0, 5.0),
    (11.7, 5.5),

    # First floppy ear (front): a long vertical loop dropping past the chin
    (11.5, 5.5),     # ear 1 base front
    (11.0, 4.0),
    (10.7, 2.7),     # ear 1 tip — DROOPS LOW
    (11.3, 2.6),
    (11.5, 3.8),
    (11.7, 5.2),     # ear 1 base back

    # Peak between ears
    (11.0, 5.7),

    # Second floppy ear (rear): identical droop
    (10.7, 5.5),     # ear 2 base front
    (10.2, 4.0),
    (10.0, 2.7),     # ear 2 tip
    (10.6, 2.6),
    (10.8, 3.8),
    (11.0, 5.2),     # ear 2 base back

    # Top of head behind ears, then long top of back
    (10.5, 5.7),
    (8.5, 6.0),
    (6.0, 6.0),
    (3.8, 5.7),

    # Tail held UP and slightly forward (wagging)
    (3.2, 6.0),
    (2.6, 6.9),
    (2.4, 7.8),      # tail tip (high)
    (3.1, 7.9),
    (3.4, 7.0),
    (3.6, 5.7),

    # Rump down to back leg
    (4.0, 4.2),
    (4.0, 2.5),

    # Back leg (longer than cat — beagle stance)
    (4.0, 0.5),
    (4.0, 0.2),
    (5.4, 0.2),
    (5.4, 0.5),
    (5.2, 2.0),

    # Belly (long body)
    (6.8, 1.8),
    (9.3, 1.8),

    # Front leg
    (9.8, 2.0),
    (9.8, 0.5),
    (9.8, 0.2),
    (11.2, 0.2),
    (11.2, 0.5),
    (11.0, 2.0),

    # Chest curving up under the long snout
    (11.6, 2.5),
    (12.2, 3.0),
    (12.8, 3.3),
    (13.5, 3.5),
]
