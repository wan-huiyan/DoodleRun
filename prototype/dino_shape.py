"""Dino (T-Rex) outline — v7 redesign from scratch (2026-05-03).

Signature features: BIG BLOCKY HEAD held high on a long arched neck
(distinct from body) + LONG HORIZONTAL TAIL trailing behind + tiny-arm
notch under the chest. The classic T-Rex silhouette where the body sits
LOWER than the head.

Dino faces RIGHT. Trace clockwise from nose tip.
14 unique anchors. The neck arches up clearly so the head reads as
separate from the body — without that arch the silhouette becomes a
fish/dolphin.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

DINO_OUTLINE: List[Point] = [
    (12.0, 7.0),   #  1. nose tip (high, right edge)
    (12.2, 8.0),   #  2. top of head
    (10.8, 8.3),   #  3. back of head (big skull)
    (10.0, 6.8),   #  4. neck dip (steep arch — separates head from body)
    (8.5, 6.8),    #  5. shoulder hump
    (5.5, 7.0),    #  6. top of back
    (2.5, 6.6),    #  7. tail base (rump)
    (-1.5, 5.5),   #  8. TAIL TIP (long horizontal — extends way left)
    (0.5, 4.4),    #  9. under-tail back to body
    (3.0, 3.6),    # 10. bottom hind / hind-leg base
    (5.0, 4.0),    # 11. tiny-arm notch dip (downward V)
    (6.2, 3.8),    # 12. tiny-arm tip (small forward bump)
    (7.0, 4.6),    # 13. arm-to-chest
    (9.5, 5.2),    # 14. chest under neck
    (11.2, 6.4),   # 15. throat (under jaw)
    (12.0, 7.0),   # 16. close (= 1)
]
