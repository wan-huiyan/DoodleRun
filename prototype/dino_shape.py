"""Dino outline — brontosaurus body with three stegosaurus back plates.

Promoted from `dino_candidate_1` per the SHAPE_OVERHAUL_PLAN review: the
long neck creates a tall, distinctive silhouette. T-Rex (#2) and pure
stegosaurus (#4) are preserved as alternates.

Faces RIGHT. Long neck rises to a small head; three back plates accent
the spine; long tapering tail; thick legs.

Format: standard shape-file interface (OUTLINE + INTERIOR_FEATURES +
METADATA — see `prototype/shapes.py` for the registry contract).
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

OUTLINE: List[Point] = [
    # Small head perched at the top
    (15.5, 9.0),
    (15.5, 9.5),
    (14.8, 9.5),

    # Down the BACK of the long neck
    (14.0, 8.7),
    (13.0, 7.7),
    (12.0, 6.5),
    (11.0, 5.5),

    # Three back plates along the spine (Section 2.3 refinement: taller
    # plates to read at smaller scales)
    (10.5, 5.5),
    (10.0, 7.0),
    (9.5, 5.5),
    (9.0, 5.5),
    (8.5, 7.6),
    (8.0, 5.5),
    (7.5, 5.5),
    (7.0, 7.0),
    (6.5, 5.5),

    # Top of back curving down to tail
    (5.0, 5.3),
    (4.0, 5.0),

    # Long tapering tail (top side)
    (3.0, 4.7),
    (2.0, 4.5),
    (1.0, 4.3),
    (0.2, 4.1),
    (0.2, 3.7),

    # Tail underside back to rump
    (1.0, 3.7),
    (2.0, 3.8),
    (3.0, 3.7),
    (4.0, 3.5),

    # Rump down to back leg
    (4.5, 3.0),
    (5.0, 2.5),
    (5.0, 0.4),
    (5.0, 0.2),
    (6.6, 0.2),
    (6.6, 0.4),
    (6.4, 2.2),

    # Belly
    (7.6, 2.2),
    (9.0, 2.2),
    (10.5, 2.2),

    # Front leg
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

# Outline is already complex with the back plates — Section 5.3 says no
# interior features for dino.
INTERIOR_FEATURES: List[List[Point]] = []

METADATA = {
    "description": "Brontosaurus body with three back plates, long neck and tail.",
    "source": "promoted from dino_candidate_1 (hand-crafted)",
    "license": "internal",
}

# Legacy alias.
DINO_OUTLINE: List[Point] = OUTLINE
