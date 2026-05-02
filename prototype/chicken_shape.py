"""Chicken outline — doodle style (rooster weathervane silhouette).

Faces RIGHT. Designed by the "ONE signature feature" principle, but the
chicken benefits from THREE coordinated features all going TALL:
1. THREE-PEAK COMB on top of the head — peaks ~2 units tall (very prominent).
2. THREE TAIL FEATHERS fanning UP and back from the rump — also tall,
   creating the rooster weathervane silhouette.
3. TWO THIN STICK LEGS — barely-wider-than-zero peninsulas, not the
   fat rectangles a quadruped uses.

Plump round body sits between the comb (front-top) and tail (back-top).
Trace order: beak → comb → back of head → top of body → tail feathers →
underside back → rump → back leg → small belly → front leg → breast →
wattle → close.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

CHICKEN_OUTLINE: List[Point] = [
    # Beak tip
    (10.5, 5.0),
    # Top of beak
    (10.0, 5.4),
    (9.7, 5.6),

    # ---- THREE TALL COMB PEAKS on top of the head ------------------------
    (9.5, 5.6),
    (9.4, 7.5),      # peak 1 (front)
    (9.0, 5.8),
    (8.7, 7.8),      # peak 2 (tallest, middle)
    (8.4, 5.8),
    (8.2, 7.4),      # peak 3 (rear)
    (7.8, 5.6),

    # Back of head down through short neck
    (7.4, 5.3),
    (7.0, 4.9),

    # Top of plump body — gentle dome
    (6.0, 4.7),
    (5.0, 4.6),
    (4.0, 4.5),

    # ---- THREE TALL TAIL FEATHERS fanning UP and back -------------------
    (3.5, 4.9),
    (2.6, 6.8),      # feather 1 (back-most, tall)
    (2.5, 4.7),
    (1.6, 6.5),      # feather 2 (middle, taller)
    (1.5, 4.4),
    (0.5, 6.0),      # feather 3 (forward, shorter)
    (0.5, 4.0),

    # Underside of tail back into rump
    (1.5, 3.6),
    (3.0, 3.2),
    (4.0, 2.9),

    # Round rump down to leg
    (4.5, 2.2),
    (4.7, 1.5),

    # ---- THIN STICK BACK LEG (~0.3 unit wide) ---------------------------
    (4.7, 0.3),
    (4.6, 0.2),
    (5.1, 0.2),
    (5.0, 0.3),
    (4.9, 1.5),

    # Tiny belly between legs
    (5.7, 1.7),
    (6.3, 1.7),

    # ---- THIN STICK FRONT LEG ------------------------------------------
    (6.9, 1.5),
    (6.8, 0.3),
    (6.7, 0.2),
    (7.2, 0.2),
    (7.1, 0.3),
    (7.0, 1.5),

    # Plump breast curving up to throat
    (7.8, 2.0),
    (8.4, 3.0),
    (8.8, 3.8),
    (9.2, 4.4),

    # Wattle (small bump under beak)
    (9.2, 4.7),
    (9.6, 4.8),

    # Underside of beak back to tip
    (10.0, 4.9),
    (10.5, 5.0),
]
