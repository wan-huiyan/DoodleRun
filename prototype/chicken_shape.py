"""Chicken outline — kawaii cartoon rooster from freesvg.org.

Source SVG: freesvg.org "Cartoon Rooster"
(https://freesvg.org/cartoon-rooster). License: public domain (CC0).

Promoted from `chicken_candidate_1` per the SHAPE_OVERHAUL_PLAN review:
chubby rooster with jagged comb, beak, layered tail feathers, and two
thin legs. Generated via shapely-union of comb + body + wing + tail +
legs sub-paths.

Format: standard shape-file interface (OUTLINE + INTERIOR_FEATURES +
METADATA — see `prototype/shapes.py` for the registry contract).
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

OUTLINE: List[Point] = [
    (1.83, 10.85),
    (0.00, 7.80),
    (0.28, 7.04),
    (1.09, 6.83),
    (0.30, 5.09),
    (0.44, 3.47),
    (0.94, 2.81),
    (1.80, 2.25),
    (4.03, 1.67),
    (3.93, 1.17),
    (2.75, 0.89),
    (3.82, 0.70),
    (2.92, 0.25),
    (4.70, 0.55),
    (5.53, 0.47),
    (4.76, 0.00),
    (6.76, 0.44),
    (6.33, 0.94),
    (6.37, 1.63),
    (8.65, 2.22),
    (9.94, 3.52),
    (10.45, 5.51),
    (11.04, 6.24),
    (10.43, 6.76),
    (10.98, 7.18),
    (11.04, 7.56),
    (10.31, 7.89),
    (11.17, 8.29),
    (11.51, 9.00),
    (11.12, 9.44),
    (10.10, 9.49),
    (11.71, 10.10),
    (12.00, 10.58),
    (11.30, 11.00),
    (10.09, 11.26),
    (8.85, 11.27),
    (7.87, 10.99),
    (7.41, 10.58),
    (7.16, 9.80),
    (7.41, 7.55),
    (6.28, 7.27),
    (5.86, 7.35),
    (6.13, 7.34),
    (5.51, 7.99),
    (5.28, 9.88),
    (5.54, 10.42),
    (5.28, 11.66),
    (5.00, 11.99),
    (4.38, 12.09),
    (4.15, 12.74),
    (3.51, 12.84),
    (2.89, 12.14),
    (1.95, 12.08),
    (1.73, 11.63),
    (1.83, 10.85),
]

# Eye dot near the head (Section 5.3).
INTERIOR_FEATURES: List[List[Point]] = [
    [
        (3.20, 11.00),
        (3.30, 11.10),
        (3.20, 11.00),
    ],
]

METADATA = {
    "description": "Kawaii cartoon rooster with jagged comb, beak, tail feathers.",
    "source": "promoted from chicken_candidate_1 (freesvg.org via tools/svg_to_shape.py)",
    "license": "CC0 (freesvg.org)",
}

# Legacy alias.
CHICKEN_OUTLINE: List[Point] = OUTLINE
