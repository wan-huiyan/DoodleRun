"""Cat outline — kawaii cartoon cat from freesvg.org.

Source SVG: freesvg.org "Cute Cat Vector Image"
(https://freesvg.org/cute-cat-vector-image). License: public domain (CC0).

Promoted from `cat_candidate_1` per the SHAPE_OVERHAUL_PLAN review:
classic kawaii blob with pointy triangle ears and a tail curling over the
back. Generated via shapely-union of body + head + ears + tail sub-paths.

Format: standard shape-file interface (OUTLINE + INTERIOR_FEATURES +
METADATA — see `prototype/shapes.py` for the registry contract).
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

OUTLINE: List[Point] = [
    (8.62, 7.25),
    (9.59, 8.20),
    (10.26, 8.35),
    (10.72, 7.72),
    (11.13, 6.39),
    (11.75, 5.35),
    (12.00, 4.18),
    (11.96, 2.72),
    (11.63, 1.57),
    (11.02, 0.75),
    (9.60, 0.17),
    (7.63, 0.00),
    (5.68, 0.30),
    (4.89, 0.63),
    (4.45, 1.02),
    (3.12, 0.46),
    (2.03, 0.27),
    (1.15, 0.42),
    (0.49, 0.91),
    (0.00, 2.12),
    (0.04, 2.46),
    (0.30, 2.67),
    (0.85, 2.64),
    (1.62, 2.33),
    (1.97, 1.50),
    (2.46, 1.14),
    (3.15, 1.17),
    (4.08, 1.63),
    (3.73, 3.11),
    (3.83, 4.82),
    (4.18, 5.79),
    (4.69, 6.47),
    (5.08, 7.68),
    (5.52, 8.32),
    (5.80, 8.39),
    (6.19, 8.22),
    (7.20, 7.24),
    (8.62, 7.25),
]

# Two short whisker strokes near the muzzle. These are tiny out-and-back
# pokes anchored close to the outline so they don't add measurable distance
# to the route.
INTERIOR_FEATURES: List[List[Point]] = [
    [
        (10.20, 3.20),
        (10.80, 3.20),
        (10.20, 3.20),
    ],
    [
        (10.20, 2.60),
        (10.80, 2.60),
        (10.20, 2.60),
    ],
]

METADATA = {
    "description": "Kawaii cartoon cat with pointy triangle ears and a curled tail; whiskers.",
    "source": "promoted from cat_candidate_1 (freesvg.org via tools/svg_to_shape.py)",
    "license": "CC0 (freesvg.org)",
}

# Legacy alias.
CAT_OUTLINE: List[Point] = OUTLINE
