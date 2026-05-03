"""Dog outline — v7 redesign from scratch (2026-05-03).

Signature features: LONG SNOUT (rectangular, jutting forward) + SINGLE
PERKY TRIANGLE EAR (German-shepherd / terrier style — pointed forward) +
RAISED TAIL UP. No legs.

Design note: floppy ears can't be drawn with a closed polyline without
creating a body-notch artifact (looks like a knife slot, not an ear).
The single perky ear distinguishes the dog from the cat (which has two
ears) and combined with the long rectangular snout and longer body
reads unambiguously as a dog.

Dog faces RIGHT. Trace clockwise from nose tip.
12 unique anchors.
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

DOG_OUTLINE: List[Point] = [
    (10.5, 4.7),   #  1. nose tip (right edge)
    (10.5, 5.7),   #  2. top of long snout
    (8.7, 5.7),    #  3. snout-to-skull junction (forehead notch up)
    (8.7, 6.5),    #  4. base of perky ear (front)
    (8.4, 7.6),    #  5. PERKY EAR TIP (single triangle, pointed up)
    (8.0, 6.6),    #  6. base of perky ear (back)
    (7.0, 6.5),    #  7. back of skull / start of long back
    (3.5, 6.2),    #  8. top of back
    (1.5, 7.8),    #  9. TAIL TIP (raised happy — tall spike)
    (1.5, 5.7),    # 10. rump (down from tail tip)
    (1.8, 3.4),    # 11. bottom hind
    (8.5, 3.4),    # 12. bottom front
    (10.0, 3.9),   # 13. chest curve
    (10.5, 4.7),   # 14. close (= 1)
]
