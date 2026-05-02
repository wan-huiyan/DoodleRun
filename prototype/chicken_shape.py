"""Chicken outline — doodle style.

Faces RIGHT. Signature features (in order of importance):
1. Three-peak COMB on top of the head — jagged.
2. Pointy BEAK forward (with a wattle bump under it).
3. Tail FEATHERS fanning UP and back — three rising peaks.
4. UPRIGHT plump body (taller than wide, egg-shaped) with two thin
   stick legs going straight down to small feet.

The "upright body" is what distinguishes this from a quadruped silhouette.
Trace order: beak → comb → back of head → back-and-down to tail → tail
feathers → underside back into rump → back leg → small belly between legs
→ front leg → breast → wattle → close.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

CHICKEN_OUTLINE: List[Point] = [
    # Beak tip (forward)
    (11.0, 4.8),
    # Top of beak meeting forehead
    (10.4, 5.2),
    (10.2, 5.4),

    # Three-peak COMB on top of head (head sits high on body)
    (10.0, 5.4),
    (9.9, 6.6),      # comb peak 1 (forward)
    (9.5, 5.6),
    (9.3, 7.0),      # comb peak 2 (tallest)
    (8.9, 5.6),
    (8.7, 6.4),      # comb peak 3 (rear)
    (8.4, 5.4),

    # Back of head down through short neck into the body's back
    (8.0, 5.0),
    (7.6, 4.6),
    (7.0, 4.4),

    # Top of plump body — gentle slope down toward the tail
    (6.0, 4.5),
    (5.0, 4.4),
    (4.2, 4.3),

    # ---- Tail feathers — three rising peaks fanning up and back ----
    (3.8, 4.7),
    (3.0, 6.4),      # feather 1 (back-most, tallest)
    (2.9, 4.5),
    (2.3, 5.6),      # feather 2 (middle)
    (2.2, 4.3),
    (1.7, 5.0),      # feather 3 (forward, shortest)
    (1.6, 4.0),

    # Underside of tail back into rump
    (2.4, 3.6),
    (3.5, 3.2),
    (4.5, 2.9),

    # Round rump curving down to back leg
    (5.0, 2.3),
    (5.3, 1.6),

    # Back leg (thin stick straight down + small foot)
    (5.3, 0.4),
    (5.1, 0.2),      # back of foot
    (6.5, 0.2),      # toe
    (6.2, 0.5),
    (6.0, 1.6),

    # Small belly between legs
    (6.8, 2.0),
    (7.3, 2.0),

    # Front leg (thin stick + foot)
    (7.8, 1.6),
    (7.8, 0.5),
    (7.5, 0.2),
    (9.0, 0.2),
    (8.7, 0.5),
    (8.5, 1.6),

    # Plump breast curving up to throat
    (9.2, 2.4),
    (9.6, 3.2),
    (9.9, 4.0),

    # Wattle (small bump hanging under the beak)
    (9.9, 4.3),
    (10.3, 4.4),

    # Underside of beak back to tip
    (10.6, 4.6),
    (11.0, 4.8),
]
