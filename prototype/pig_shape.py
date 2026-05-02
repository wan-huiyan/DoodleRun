"""Pig outline — side-profile pig with one prominent floppy round ear.

Promoted from `pig_candidate_4` per the SHAPE_OVERHAUL_PLAN review:
candidate 4's side profile reads clearly at thumbnail scale and the round
floppy ear is a strong differentiator. The curly-tail seated pose
(candidate 3) is preserved as an alternate — see `pig_candidate_3.py`.

Format: standard shape-file interface (OUTLINE + INTERIOR_FEATURES +
METADATA — see `prototype/shapes.py` for the registry contract).
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

OUTLINE: List[Point] = [
    (12.000, 3.500),
    (12.000, 4.400),
    (11.300, 4.600),
    (10.800, 5.200),
    (10.400, 5.700),
    # Floppy round ear (loop)
    (9.474, 6.280),
    (9.136, 6.171),
    (8.840, 5.975),
    (8.608, 5.705),
    (8.458, 5.383),
    (8.400, 5.032),
    (8.440, 4.679),
    (8.574, 4.350),
    (8.792, 4.069),
    (9.078, 3.858),
    (9.411, 3.733),
    (9.765, 3.702),
    (10.114, 3.768),
    (10.432, 3.926),
    (10.696, 4.164),
    # Back of head into back
    (10.600, 5.300),
    (10.800, 5.600),
    (10.500, 6.000),
    (8.500, 6.100),
    (5.000, 6.000),
    # Rump up to short tail bump
    (3.500, 5.800),
    (2.800, 6.400),
    (2.200, 6.000),
    (2.600, 5.400),
    (3.200, 5.600),
    # Round belly curve (Section 2.3 refinement)
    (3.700, 5.200),
    (3.700, 3.000),
    # Back leg
    (3.800, 0.400),
    (3.800, 0.200),
    (5.000, 0.200),
    (5.000, 0.400),
    (4.900, 1.800),
    # Belly through to front leg
    (6.500, 1.700),
    (9.000, 1.700),
    (9.500, 1.900),
    (9.500, 0.400),
    (9.500, 0.200),
    (10.700, 0.200),
    (10.700, 0.400),
    (10.500, 1.900),
    # Chest up to snout
    (11.200, 2.400),
    (11.700, 3.000),
    (12.000, 3.500),
]

# Two nostril dots at the snout — short out-and-back strokes (Section 5.3:
# keep interior features minimal and close to the outline).
INTERIOR_FEATURES: List[List[Point]] = [
    [
        (11.700, 3.700),
        (11.800, 3.800),
        (11.700, 3.700),
    ],
    [
        (11.700, 4.000),
        (11.800, 4.100),
        (11.700, 4.000),
    ],
]

METADATA = {
    "description": "Side-profile pig with one prominent floppy round ear and two nostril dots.",
    "source": "promoted from pig_candidate_4 (hand-crafted via tools/gen_candidates.py)",
    "license": "internal",
}

# Legacy alias — keep in sync with OUTLINE so older callers that imported
# `PIG_OUTLINE` directly don't break.
PIG_OUTLINE: List[Point] = OUTLINE
