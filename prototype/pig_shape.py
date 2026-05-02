"""Pig outline as ordered (x, y) waypoints for a continuous tracing path.

Pig faces right. The path starts at the snout tip, traces clockwise:
snout → forehead → ear → top of back → curly tail → rump → back leg →
belly → front leg → chest → underside of snout → close.

Design choices for street-routing readability:
- 2 visible legs (side-profile convention) instead of 4. Four legs collapse
  into a fence pattern when each leg is shorter than two city blocks.
- Wide legs (~2.5 units) and tall (~1.8 units) so each foot is a clear
  out-and-back of 2-3 blocks.
- Ear poking above the back line by ~1.0 units so the head silhouette
  registers when projected to a city grid.
- Curly tail with 4 control points to suggest a spiral.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

PIG_OUTLINE: List[Point] = [
    # Snout tip and top of snout
    (13.0, 4.0),
    (13.0, 4.8),
    (12.0, 5.1),

    # Forehead, top of head, ear
    (11.0, 5.4),
    (10.2, 5.7),
    (9.8, 6.8),    # ear back
    (10.7, 7.2),   # ear tip
    (11.0, 5.9),   # ear front (back to head)

    # Top of back from head to tail base
    (9.0, 5.7),
    (7.0, 5.8),
    (5.0, 5.7),
    (3.0, 5.5),

    # Curly tail
    (1.8, 5.7),
    (1.0, 6.3),    # outer top of curl
    (0.4, 5.8),    # outer left
    (0.4, 5.0),    # outer bottom
    (1.0, 4.8),    # inner bottom
    (1.4, 5.2),    # inner side
    (1.7, 5.4),    # back near base

    # Rump down to back leg
    (2.0, 4.5),
    (2.2, 3.0),

    # Back leg (wide, deep out-and-back)
    (2.5, 1.5),
    (2.5, 0.2),    # foot bottom outer
    (5.0, 0.2),    # foot bottom inner
    (5.0, 1.8),    # leg inner top

    # Belly between legs
    (7.0, 2.0),
    (8.5, 2.0),

    # Front leg
    (9.0, 1.8),
    (9.0, 0.2),    # foot bottom outer
    (11.5, 0.2),   # foot bottom inner
    (11.5, 1.8),   # leg inner top

    # Chest curve up to chin
    (12.0, 2.5),
    (12.5, 3.2),
    (12.8, 3.7),
    (13.0, 4.0),   # close to snout tip
]
