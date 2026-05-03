"""Chicken outline — v7 redesign from scratch (2026-05-03).

Signature features: COMB on top (single sharp peak) + BEAK pointing right +
TAIL FEATHERS curving up behind. No legs.

Chicken faces RIGHT. Trace clockwise. Polyline starts and closes at the
under-beak point so the beak tip is a simple right-pointing triangle made
from anchors 1 → 2 (beak tip) → 3.

14 unique anchors. The comb is a single tall spike — stepped combs collapse
on street grids. The beak is a small forward triangle. The tail feathers are
a single curved spike rising up and back over the body.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

CHICKEN_OUTLINE: List[Point] = [
    (9.5, 5.0),    #  1. under-beak (start/close anchor)
    (10.5, 5.5),   #  2. BEAK TIP (right edge — sharp point)
    (9.5, 5.6),    #  3. above-beak / front of neck top
    (9.0, 6.0),    #  4. neck rising
    (8.8, 6.5),    #  5. base of comb (front)
    (8.5, 7.6),    #  6. COMB SPIKE TIP (tall single peak — signature)
    (8.0, 6.5),    #  7. base of comb (back)
    (7.5, 6.3),    #  8. back of head
    (5.0, 6.4),    #  9. top of back
    (3.0, 6.6),    # 10. tail-feather base
    (1.0, 8.0),    # 11. TAIL FEATHER TIP (raised high — signature curve)
    (2.5, 5.6),    # 12. tail back to body
    (3.0, 3.8),    # 13. bottom hind
    (8.5, 3.8),    # 14. bottom front
    (9.5, 5.0),    # 15. close (= 1, under-beak)
]
