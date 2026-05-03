"""Cat outline — v7 redesign from scratch (2026-05-03).

Signature features: TWO POINTED EARS + RAISED TAIL. No legs (loafed cat).
Cat faces RIGHT. Trace clockwise from chin.

13 unique anchors. Each ear is a tight upward triangle (3 anchors). The tail
is a single raised spike (2 anchors out, 1 anchor return).
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

CAT_OUTLINE: List[Point] = [
    (8.0, 4.4),    #  1. chin tip (right edge)
    (7.6, 5.2),    #  2. throat / neck up
    (7.5, 5.6),    #  3. base of right ear
    (8.3, 6.9),    #  4. RIGHT EAR TIP (sharp!)
    (7.0, 5.8),    #  5. between-ears dip
    (5.7, 6.9),    #  6. LEFT EAR TIP (sharp!)
    (5.5, 5.6),    #  7. base of left ear
    (3.5, 5.4),    #  8. back of neck / start of back
    (2.0, 5.2),    #  9. rump
    (0.4, 7.8),    # 10. TAIL TIP (raised high — signature spike)
    (1.5, 5.0),    # 11. tail base back to body
    (2.0, 3.2),    # 12. bottom hind
    (7.5, 3.2),    # 13. bottom front
    (8.0, 4.4),    # 14. close (= 1)
]
