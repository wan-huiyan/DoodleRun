"""Dog outline — beagle-stance side-profile dog with one big floppy ear.

Promoted from `dog_candidate_1` per the SHAPE_OVERHAUL_PLAN review: the
drooping floppy ear is the key cat-vs-dog differentiator at thumbnail
scale. The sitting/perky-eared candidate (3) is preserved as an alternate
— see `dog_candidate_3.py`.

Faces RIGHT. Long horizontal body (beagle/dachshund stance), long
rectangular snout, tail held UP and slightly forward.

Format: standard shape-file interface (OUTLINE + INTERIOR_FEATURES +
METADATA — see `prototype/shapes.py` for the registry contract).
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

OUTLINE: List[Point] = [
    # Snout tip
    (13.0, 3.5),
    # Top of long rectangular snout
    (13.0, 4.5),
    (12.0, 4.7),

    # Forehead up to top of head
    (11.5, 5.0),
    (11.0, 5.5),

    # ONE BIG FLOPPY EAR — drooping forward from the back of the head,
    # integrated into the head silhouette as a downward U-shape.
    (10.5, 5.2),
    (9.8, 4.0),
    (9.5, 2.8),
    (10.2, 2.6),
    (10.5, 4.0),
    (10.7, 5.0),

    # Top of head behind ear, then long top of back
    (10.5, 5.7),
    (8.5, 5.8),
    (6.0, 5.8),
    (3.5, 5.5),

    # Tail UP and slightly forward (wagging)
    (3.0, 5.7),
    (2.5, 6.6),
    (2.5, 7.6),
    (3.2, 7.6),
    (3.5, 6.6),
    (3.7, 5.5),

    # Rump down
    (4.0, 4.0),
    (4.0, 2.5),

    # Back leg
    (4.0, 0.4),
    (4.0, 0.2),
    (5.3, 0.2),
    (5.3, 0.4),
    (5.2, 2.0),

    # Belly
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

# Single eye dot near the head — tiny out-and-back stroke.
INTERIOR_FEATURES: List[List[Point]] = [
    [
        (11.4, 4.8),
        (11.5, 4.9),
        (11.4, 4.8),
    ],
]

METADATA = {
    "description": "Side-profile dog with one big floppy ear, long body, tail-up.",
    "source": "promoted from dog_candidate_1 (hand-crafted)",
    "license": "internal",
}

# Legacy alias.
DOG_OUTLINE: List[Point] = OUTLINE
