"""Pig outline — v7 redesign from scratch (2026-05-03).

Design rules (from gps-art-tangled-trace-fix skill + GH issue #1):
- 13 anchor points TOTAL — bold sweeping curves only.
- Signature features: CHUNKY ROUND BODY (aspect ~1.5:1, not fish-shaped) +
  raised SNOUT face on the front + clearly visible EAR triangle on top of
  the head + back-hook curly TAIL.
- NO legs (4-leg silhouettes collapse into noise on street grids).

Pig faces RIGHT. Trace clockwise from snout tip.
13 unique anchors. Body is intentionally chunky — taller relative to its
length than the v1-v6 fish-shaped pigs that did not read as pigs.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

PIG_OUTLINE: List[Point] = [
    (7.5, 4.0),    #  1. snout tip (right edge — projects forward)
    (7.5, 5.4),    #  2. top of snout (vertical front face)
    (6.4, 5.7),    #  3. snout-to-head junction
    (6.2, 7.2),    #  4. EAR TIP (clear upward triangle, big)
    (5.4, 5.8),    #  5. ear back to head
    (3.5, 6.6),    #  6. top of back (high arc)
    (1.0, 6.0),    #  7. rump (tail base)
    (-0.2, 6.8),   #  8. TAIL CURL outer-top
    (-0.7, 5.7),   #  9. tail curl tip
    (0.4, 5.2),    # 10. tail curl back to body (closes loop)
    (0.5, 3.0),    # 11. hind belly (lower than v6 — chunkier body)
    (4.0, 2.7),    # 12. low belly center
    (7.0, 3.3),    # 13. chest
    (7.5, 4.0),    # 14. close (= 1)
]
