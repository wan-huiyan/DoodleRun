"""Generate candidate shape files (candidate_2 through candidate_5) for each animal.

These hand-crafted candidates fill the gap until enough source SVGs are
ingested through `tools/svg_to_shape.py --with-interior` to populate the
catalog automatically. They follow the SAME interface the SVG pipeline
emits — `OUTLINE` + optional `INTERIOR_FEATURES` + `METADATA` — so the
shapes registry treats them uniformly with SVG-derived shapes.

Run from repo root: `python tools/gen_candidates.py`

Re-running overwrites the candidate files. Hand edits should live elsewhere
or be reflected back into this generator.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Tuple

Point = Tuple[float, float]

PROTO = Path(__file__).resolve().parent.parent / "prototype"


# ──────────────────────────────────────────────────────────────────────────────
# Geometry helpers (parametric — same building blocks the SVG pipeline could
# emit if it were drawing primitives instead of sampling source paths).
# ──────────────────────────────────────────────────────────────────────────────

def arc(cx: float, cy: float, r: float, deg_start: float, deg_end: float, n: int = 16) -> List[Point]:
    pts: List[Point] = []
    for i in range(n + 1):
        t = i / n
        a = math.radians(deg_start + t * (deg_end - deg_start))
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def circle(cx: float, cy: float, r: float, n: int = 24) -> List[Point]:
    return arc(cx, cy, r, 0, 360, n)


# ──────────────────────────────────────────────────────────────────────────────
# Candidate definitions — each returns (outline, interior_features, description)
# ──────────────────────────────────────────────────────────────────────────────

# PIG ─────────────────────────────────────────────────────────────────────────

def pig_candidate_2():
    outline: List[Point] = []
    outline.append((3.0, 8.0))
    outline += arc(2.0, 9.0, 1.6, 0, 200, 14)
    outline.append((1.5, 8.5))
    outline.append((1.2, 7.5))
    outline += arc(6.0, 5.5, 4.8, 175, 230, 10)
    outline.append((4.2, 1.5))
    outline.append((6.0, 1.0))
    outline.append((7.8, 1.5))
    outline += arc(6.0, 5.5, 4.8, 310, 355, 10)
    outline.append((10.8, 7.5))
    outline.append((10.5, 8.5))
    outline.append((9.0, 8.0))
    outline += arc(10.0, 9.0, 1.6, 340, 540, 14)
    outline.append((9.0, 8.0))
    outline.append((7.5, 7.6))
    # Snout disc — part of the silhouette (the nose pad)
    outline += circle(6.0, 4.8, 1.4, 18)
    outline.append((4.5, 7.6))
    outline.append((3.0, 8.0))
    features = [
        # Left nostril
        [(5.5, 4.5), (5.4, 4.9), (5.5, 4.5)],
        # Right nostril
        [(6.5, 4.5), (6.6, 4.9), (6.5, 4.5)],
    ]
    return outline, features, "Pig face — round flappy ears, snout disc, nostril dots"


def pig_candidate_3():
    outline: List[Point] = []
    outline.append((11.5, 4.5))
    outline.append((11.5, 5.5))
    outline.append((10.8, 5.7))
    outline.append((10.2, 6.6))
    outline += arc(9.5, 7.0, 0.9, -10, 200, 10)
    outline.append((9.0, 6.8))
    outline += arc(6.0, 4.5, 3.5, 60, 175, 14)
    # Curly tail bump on outline
    outline.append((2.4, 4.7))
    outline.append((2.0, 5.2))
    outline.append((1.6, 4.8))
    outline.append((2.0, 4.4))
    outline.append((2.4, 4.5))
    outline += arc(6.0, 4.5, 3.5, 175, 230, 8)
    outline.append((4.2, 1.0))
    outline.append((4.2, 0.4))
    outline.append((5.4, 0.4))
    outline.append((5.4, 1.5))
    outline.append((7.4, 1.5))
    outline.append((7.6, 0.8))
    outline.append((7.6, 0.4))
    outline.append((8.8, 0.4))
    outline.append((8.8, 1.5))
    outline += arc(9.5, 4.0, 1.6, 235, 340, 10)
    outline.append((11.0, 4.4))
    outline.append((11.5, 4.5))
    features = [
        [(11.0, 4.8), (11.0, 5.0), (11.0, 4.8)],
        [(11.0, 5.3), (11.0, 5.5), (11.0, 5.3)],
    ]
    return outline, features, "Chubby seated pig — curly tail, ear bump, nostril dots"


def pig_candidate_4():
    outline: List[Point] = []
    outline.append((12.0, 3.5))
    outline.append((12.0, 4.4))
    outline.append((11.3, 4.6))
    outline.append((10.8, 5.2))
    outline.append((10.4, 5.7))
    outline += arc(9.7, 5.0, 1.3, 100, 320, 14)
    outline.append((10.6, 5.3))
    outline.append((10.8, 5.6))
    outline.append((10.5, 6.0))
    outline.append((8.5, 6.1))
    outline.append((5.0, 6.0))
    # Curly tail bump on outline
    outline.append((3.5, 5.8))
    outline.append((2.8, 6.4))
    outline.append((2.2, 6.0))
    outline.append((2.6, 5.4))
    outline.append((3.2, 5.6))
    outline.append((3.8, 5.2))
    outline.append((3.8, 3.0))
    outline.append((3.8, 0.4))
    outline.append((3.8, 0.2))
    outline.append((5.0, 0.2))
    outline.append((5.0, 0.4))
    outline.append((4.9, 1.8))
    outline.append((6.5, 1.7))
    outline.append((9.0, 1.7))
    outline.append((9.5, 1.9))
    outline.append((9.5, 0.4))
    outline.append((9.5, 0.2))
    outline.append((10.7, 0.2))
    outline.append((10.7, 0.4))
    outline.append((10.5, 1.9))
    outline.append((11.2, 2.4))
    outline.append((11.7, 3.0))
    outline.append((12.0, 3.5))
    features = [
        [(11.4, 3.7), (11.4, 3.9), (11.4, 3.7)],
        [(11.4, 4.0), (11.4, 4.2), (11.4, 4.0)],
    ]
    return outline, features, "Side-profile pig with one prominent floppy round ear"


def pig_candidate_5():
    outline: List[Point] = []
    outline.append((6.0, 10.0))
    outline += arc(8.0, 10.0, 1.4, 180, 0, 12)
    outline += arc(6.0, 5.0, 5.0, 50, -50, 14)
    outline.append((6.0, -0.2))
    outline += arc(6.0, 5.0, 5.0, 230, 130, 14)
    outline += arc(4.0, 10.0, 1.4, 180, 360, 12)
    outline.append((6.0, 10.0))
    features = [
        # Snout disc (interior detail, separate from outline)
        circle(6.0, 3.5, 1.8, 16),
        # Nostrils
        [(5.4, 3.3), (5.3, 3.5), (5.4, 3.3)],
        [(6.6, 3.3), (6.7, 3.5), (6.6, 3.3)],
    ]
    return outline, features, "Pig face 3/4 view — big snout disc, two round ears on top"


# CAT ─────────────────────────────────────────────────────────────────────────

def cat_candidate_2():
    outline: List[Point] = []
    outline.append((2.5, 7.0))
    outline.append((2.0, 9.5))
    outline.append((4.0, 7.5))
    outline.append((6.0, 8.0))
    outline.append((8.0, 7.5))
    outline.append((10.0, 9.5))
    outline.append((9.5, 7.0))
    outline += arc(6.0, 5.0, 4.5, 30, -90, 12)
    outline.append((6.0, 0.5))
    outline += arc(6.0, 5.0, 4.5, 270, 150, 12)
    outline.append((2.5, 7.0))
    features = [
        # Nose triangle
        [(5.7, 4.8), (6.3, 4.8), (6.0, 4.5), (6.0, 5.0)],
        # 3 left whiskers
        [(2.0, 4.8)],
        [(2.0, 4.0)],
        [(2.0, 3.2)],
        # 3 right whiskers
        [(10.0, 4.8)],
        [(10.0, 4.0)],
        [(10.0, 3.2)],
    ]
    return outline, features, "Cat face — pointy ears, whiskers, nose triangle"


def cat_candidate_3():
    outline: List[Point] = []
    outline.append((10.0, 7.0))
    outline.append((10.5, 8.0))
    outline.append((11.0, 7.0))
    outline.append((11.5, 6.5))
    outline.append((11.8, 5.8))
    outline.append((11.2, 5.5))
    outline.append((10.8, 5.2))
    outline.append((10.5, 3.0))
    outline.append((10.5, 0.5))
    outline.append((9.5, 0.5))
    outline.append((9.5, 2.5))
    outline.append((6.0, 1.5))
    outline.append((4.0, 0.5))
    outline.append((3.0, 0.5))
    outline.append((3.0, 2.5))
    outline.append((2.5, 4.5))
    outline.append((1.5, 5.0))
    outline.append((1.0, 7.0))
    outline.append((1.5, 8.5))
    # Tail curl as outline detail
    outline.append((2.5, 8.2))
    outline.append((2.8, 7.0))
    outline.append((2.0, 6.5))
    outline.append((1.8, 6.8))
    outline.append((2.0, 7.5))
    outline.append((2.5, 6.0))
    outline.append((4.0, 6.5))
    outline.append((6.0, 6.8))
    outline.append((8.0, 6.8))
    outline.append((9.5, 6.7))
    outline.append((9.5, 7.8))
    outline.append((10.0, 7.0))
    features = [
        # Eye dot
        [(11.4, 6.5), (11.4, 6.3), (11.2, 6.4)],
    ]
    return outline, features, "Sitting cat — arched back, vertical curled tail, eye dot"


def cat_candidate_4():
    outline: List[Point] = []
    outline.append((1.5, 6.5))
    outline.append((2.0, 11.0))
    outline.append((4.5, 7.5))
    outline.append((6.0, 7.8))
    outline.append((7.5, 7.5))
    outline.append((10.0, 11.0))
    outline.append((10.5, 6.5))
    outline += arc(6.0, 4.5, 4.5, 25, -90, 14)
    outline.append((6.0, 0.0))
    outline += arc(6.0, 4.5, 4.5, 270, 155, 14)
    outline.append((1.5, 6.5))
    features = [
        circle(4.5, 5.5, 0.4, 10),
        circle(7.5, 5.5, 0.4, 10),
        [(5.7, 4.2), (6.3, 4.2), (6.0, 3.7), (6.0, 4.0)],
        [(1.5, 3.8)],
        [(1.5, 3.0)],
        [(1.5, 2.2)],
        [(10.5, 3.8)],
        [(10.5, 3.0)],
        [(10.5, 2.2)],
    ]
    return outline, features, "Cat face — big triangular ears, eyes, nose, whiskers"


def cat_candidate_5():
    outline: List[Point] = []
    outline.append((12.0, 4.0))
    outline.append((12.0, 4.8))
    outline.append((11.0, 5.0))
    outline.append((10.7, 5.3))
    outline.append((10.2, 6.5))
    outline.append((9.8, 5.3))
    outline.append((9.4, 5.4))
    outline.append((9.0, 6.5))
    outline.append((8.7, 5.3))
    outline.append((6.0, 5.4))
    outline.append((3.0, 5.4))
    outline.append((2.0, 5.5))
    outline.append((1.5, 7.5))
    outline.append((1.2, 8.5))
    outline.append((2.0, 8.5))
    outline.append((2.2, 7.5))
    outline.append((2.5, 5.5))
    outline.append((3.0, 4.5))
    outline.append((3.0, 3.0))
    outline.append((3.0, 0.5))
    outline.append((3.0, 0.2))
    outline.append((4.0, 0.2))
    outline.append((4.0, 0.5))
    outline.append((4.0, 2.0))
    outline.append((6.0, 2.0))
    outline.append((9.0, 2.0))
    outline.append((9.0, 0.5))
    outline.append((9.0, 0.2))
    outline.append((10.0, 0.2))
    outline.append((10.0, 0.5))
    outline.append((10.0, 2.0))
    outline.append((10.5, 3.0))
    outline.append((11.0, 3.6))
    outline.append((11.5, 3.8))
    outline.append((12.0, 4.0))
    features = [
        [(10.7, 4.7), (10.7, 4.5), (10.5, 4.6)],
        [(11.7, 4.6)],
        [(11.7, 4.2)],
        [(11.7, 3.8)],
    ]
    return outline, features, "Walking cat — long body, tail straight up, head forward"


# DOG ─────────────────────────────────────────────────────────────────────────

def dog_candidate_2():
    outline: List[Point] = []
    outline.append((6.0, 9.0))
    outline += arc(6.0, 7.0, 2.5, 90, 0, 8)
    outline.append((9.0, 6.0))
    outline += arc(9.5, 3.0, 1.5, 90, 270, 14)
    outline.append((9.0, 6.5))
    outline.append((8.0, 6.0))
    outline.append((7.5, 4.5))
    outline.append((7.0, 3.5))
    outline.append((6.5, 3.0))
    outline.append((5.5, 3.0))
    outline.append((5.0, 3.5))
    outline.append((4.5, 4.5))
    outline.append((4.0, 6.0))
    outline.append((3.0, 6.5))
    outline += arc(2.5, 3.0, 1.5, 90, -90, 14)
    outline.append((3.0, 6.0))
    outline += arc(6.0, 7.0, 2.5, 180, 90, 8)
    features = [
        circle(4.8, 7.5, 0.3, 10),
        circle(7.2, 7.5, 0.3, 10),
        [(5.7, 4.5), (6.3, 4.5), (6.0, 3.9), (6.0, 4.2)],
        # Tongue
        [(5.8, 1.8), (6.2, 1.8), (6.0, 3.0)],
    ]
    return outline, features, "Dog face — basset hound, droopy ears, tongue, eyes"


def dog_candidate_3():
    outline: List[Point] = []
    outline.append((11.5, 5.5))
    outline.append((11.5, 6.3))
    outline.append((10.8, 6.5))
    outline.append((10.3, 7.2))
    outline.append((10.0, 8.5))
    outline.append((9.4, 7.0))
    outline.append((9.0, 7.2))
    outline.append((8.6, 8.0))
    outline.append((8.4, 7.0))
    outline.append((7.0, 6.5))
    outline.append((5.0, 5.5))
    outline.append((3.5, 4.5))
    outline.append((2.5, 4.5))
    outline.append((1.5, 5.2))
    outline.append((1.0, 6.0))
    outline.append((1.5, 6.3))
    outline.append((2.5, 5.5))
    outline.append((3.3, 5.2))
    outline.append((3.5, 3.0))
    outline.append((3.5, 0.5))
    outline.append((3.5, 0.2))
    outline.append((5.0, 0.2))
    outline.append((5.0, 0.5))
    outline.append((4.8, 3.0))
    outline.append((7.0, 2.5))
    outline.append((9.0, 2.0))
    outline.append((9.5, 0.5))
    outline.append((9.5, 0.2))
    outline.append((10.7, 0.2))
    outline.append((10.7, 0.5))
    outline.append((10.5, 3.0))
    outline.append((10.8, 4.0))
    outline.append((11.0, 5.0))
    outline.append((11.5, 5.5))
    features = [
        [(10.2, 6.8), (10.2, 6.6), (10.0, 6.7)],
        [(11.2, 6.0), (11.4, 6.0)],
    ]
    return outline, features, "Sitting dog full body — head up, tail behind, perky ears"


def dog_candidate_4():
    outline: List[Point] = []
    outline.append((6.0, 8.0))
    outline.append((7.0, 8.0))
    outline.append((8.5, 11.0))
    outline.append((9.0, 7.5))
    outline += arc(6.0, 5.0, 4.0, 30, -50, 10)
    outline.append((8.0, 2.5))
    outline.append((7.5, 1.5))
    outline.append((7.0, 1.0))
    outline.append((6.0, 0.5))
    outline.append((5.0, 1.0))
    outline.append((4.5, 1.5))
    outline.append((4.0, 2.5))
    outline += arc(6.0, 5.0, 4.0, 230, 150, 10)
    outline.append((3.0, 7.5))
    outline.append((3.5, 11.0))
    outline.append((5.0, 8.0))
    outline.append((6.0, 8.0))
    features = [
        circle(4.7, 5.5, 0.3, 10),
        circle(7.3, 5.5, 0.3, 10),
        [(5.6, 3.0), (6.4, 3.0), (6.0, 2.4), (6.0, 2.8)],
        [(5.7, 0.7), (6.3, 0.7), (6.0, 1.5)],
    ]
    return outline, features, "Dog face — perky pointed ears, eyes, nose, tongue"


def dog_candidate_5():
    outline: List[Point] = []
    outline.append((13.0, 3.5))
    outline.append((13.0, 4.3))
    outline.append((12.0, 4.5))
    outline.append((11.5, 5.0))
    outline.append((10.5, 5.3))
    outline.append((9.5, 6.5))
    outline.append((9.0, 5.5))
    outline.append((10.0, 5.0))
    outline.append((9.0, 5.7))
    outline.append((6.0, 5.6))
    outline.append((4.0, 5.4))
    outline.append((3.0, 5.5))
    outline.append((2.0, 7.0))
    outline.append((1.5, 8.0))
    outline.append((2.3, 8.2))
    outline.append((2.8, 7.0))
    outline.append((3.5, 5.4))
    outline.append((4.0, 5.0))
    outline.append((4.0, 3.5))
    outline.append((2.5, 1.5))
    outline.append((2.0, 1.0))
    outline.append((2.5, 0.5))
    outline.append((3.5, 1.5))
    outline.append((4.5, 2.5))
    outline.append((7.0, 1.8))
    outline.append((9.0, 1.5))
    outline.append((10.5, 0.5))
    outline.append((11.5, 0.8))
    outline.append((10.8, 1.8))
    outline.append((9.8, 2.2))
    outline.append((11.0, 2.5))
    outline.append((11.7, 3.0))
    outline.append((12.3, 3.3))
    outline.append((13.0, 3.5))
    features = [
        # Tongue
        [(12.0, 2.8), (12.4, 2.6), (12.7, 3.0), (12.5, 3.5)],
        # Eye
        [(11.2, 4.8), (11.2, 4.6), (11.0, 4.7)],
    ]
    return outline, features, "Running dog — action pose, legs spread, tail up"


# DINO ────────────────────────────────────────────────────────────────────────

def dino_candidate_2():
    outline: List[Point] = []
    outline.append((14.0, 6.5))
    outline.append((14.0, 7.5))
    outline.append((12.5, 8.0))
    outline.append((11.5, 7.5))
    outline.append((10.5, 6.5))
    outline.append((9.5, 6.0))
    outline.append((7.5, 6.2))
    outline.append((5.0, 5.8))
    outline.append((3.0, 5.0))
    outline.append((1.5, 4.4))
    outline.append((0.3, 4.0))
    outline.append((0.3, 3.6))
    outline.append((1.5, 3.6))
    outline.append((3.0, 3.4))
    outline.append((5.0, 3.0))
    outline.append((6.0, 2.5))
    outline.append((6.5, 1.5))
    outline.append((5.8, 0.4))
    outline.append((5.8, 0.2))
    outline.append((7.5, 0.2))
    outline.append((7.5, 0.4))
    outline.append((7.2, 1.5))
    outline.append((8.5, 2.5))
    outline.append((9.5, 3.5))
    # Tiny arm bump on outline
    outline.append((10.0, 3.0))
    outline.append((10.5, 3.2))
    outline.append((10.0, 3.5))
    outline.append((9.5, 3.5))
    outline.append((10.0, 4.5))
    outline.append((10.5, 5.5))
    outline.append((11.5, 6.0))
    outline.append((12.5, 6.3))
    outline.append((13.5, 6.4))
    outline.append((14.0, 6.5))
    features = [
        # Teeth zigzag
        [(13.3, 6.2), (13.1, 6.5), (12.9, 6.2), (12.7, 6.5)],
        # Eye
        [(12.7, 7.5), (12.7, 7.3), (12.5, 7.4)],
    ]
    return outline, features, "T-rex — big head, tiny arm, thick tail, teeth"


def dino_candidate_3():
    outline: List[Point] = []
    outline.append((10.0, 4.5))
    outline.append((10.5, 4.0))
    outline.append((10.0, 3.0))
    outline.append((9.0, 2.5))
    outline.append((9.5, 2.0))
    outline.append((8.5, 1.5))
    outline.append((7.0, 1.0))
    outline.append((4.5, 1.5))
    outline.append((2.5, 3.0))
    outline.append((2.0, 4.5))
    outline.append((1.5, 5.5))
    outline.append((0.5, 7.0))
    outline.append((1.5, 8.0))
    outline.append((2.5, 8.5))
    outline.append((3.0, 9.5))
    outline.append((3.5, 8.5))
    outline.append((4.5, 9.7))
    outline.append((5.5, 8.5))
    outline.append((6.5, 9.7))
    outline.append((7.5, 8.5))
    outline.append((8.5, 9.5))
    outline.append((9.0, 8.5))
    outline.append((10.0, 8.0))
    outline.append((11.0, 7.0))
    outline.append((10.5, 5.5))
    outline.append((10.0, 4.5))
    features = [
        # 3 horns
        [(5.8, 5.5), (6.2, 5.5), (6.0, 4.0)],
        [(3.5, 7.5), (4.5, 7.5), (4.0, 5.0)],
        [(7.5, 7.5), (8.5, 7.5), (8.0, 5.0)],
        # 2 eyes
        [(4.7, 4.3), (4.7, 4.1), (4.5, 4.2)],
        [(7.7, 4.3), (7.7, 4.1), (7.5, 4.2)],
    ]
    return outline, features, "Triceratops face — three horns, bumpy frill"


def dino_candidate_4():
    outline: List[Point] = []
    outline.append((13.0, 4.0))
    outline.append((13.5, 4.5))
    outline.append((13.0, 5.0))
    outline.append((11.5, 4.8))
    outline.append((10.5, 5.0))
    plate_xs = [9.5, 8.0, 6.5, 5.0, 3.5]
    plate_heights = [7.0, 8.0, 8.5, 8.0, 7.0]
    for px, ph in zip(plate_xs, plate_heights):
        outline.append((px + 0.5, 5.0))
        outline.append((px + 0.3, ph - 0.5))
        outline.append((px, ph))
        outline.append((px - 0.3, ph - 0.5))
        outline.append((px - 0.5, 5.0))
    outline.append((2.5, 4.8))
    # Tail spikes baked into outline
    outline.append((1.5, 4.5))
    outline.append((1.0, 5.5))
    outline.append((0.7, 5.0))
    outline.append((1.0, 4.4))
    outline.append((0.5, 5.3))
    outline.append((0.2, 4.8))
    outline.append((0.2, 4.2))
    outline.append((0.2, 3.8))
    outline.append((1.5, 3.8))
    outline.append((3.0, 3.6))
    outline.append((4.0, 3.0))
    outline.append((4.5, 2.5))
    outline.append((4.5, 0.4))
    outline.append((4.5, 0.2))
    outline.append((6.0, 0.2))
    outline.append((6.0, 0.4))
    outline.append((5.8, 2.4))
    outline.append((8.0, 2.4))
    outline.append((10.0, 2.4))
    outline.append((10.5, 2.4))
    outline.append((10.5, 0.4))
    outline.append((10.5, 0.2))
    outline.append((12.0, 0.2))
    outline.append((12.0, 0.4))
    outline.append((11.8, 2.5))
    outline.append((12.3, 3.2))
    outline.append((12.7, 3.7))
    outline.append((13.0, 4.0))
    features = []  # spikes & plates already part of silhouette
    return outline, features, "Stegosaurus — five plates, thagomizer spikes"


def dino_candidate_5():
    outline: List[Point] = []
    outline.append((6.0, 7.5))
    outline.append((6.0, 8.5))
    outline.append((5.5, 9.0))
    outline.append((4.5, 10.0))
    outline.append((4.0, 8.5))
    outline.append((4.5, 8.0))
    outline.append((4.0, 7.5))
    outline.append((1.0, 7.0))
    outline.append((-1.0, 8.0))
    outline.append((-2.0, 7.5))
    outline.append((-1.0, 7.0))
    outline.append((1.0, 6.5))
    outline.append((3.0, 6.0))
    outline.append((4.0, 5.5))
    outline.append((4.0, 4.0))
    outline.append((4.5, 3.5))
    outline.append((5.5, 4.0))
    outline.append((5.5, 5.5))
    outline.append((6.5, 6.0))
    outline.append((8.5, 6.5))
    outline.append((10.5, 7.0))
    outline.append((13.0, 8.0))
    outline.append((14.0, 7.5))
    outline.append((13.0, 7.0))
    outline.append((10.5, 7.0))
    outline.append((8.5, 7.3))
    outline.append((6.5, 7.5))
    outline.append((6.0, 8.0))
    outline.append((6.0, 7.5))
    features = [
        [(5.7, 8.3), (5.7, 8.1), (5.5, 8.2)],
    ]
    return outline, features, "Pterodactyl — spread wings, crest, sharp beak"


# CHICKEN ─────────────────────────────────────────────────────────────────────

def chicken_candidate_2():
    outline: List[Point] = []
    outline.append((3.0, 8.0))
    outline.append((3.5, 9.5))
    outline.append((4.5, 8.5))
    outline.append((5.0, 10.0))
    outline.append((6.0, 8.5))
    outline.append((6.5, 10.2))
    outline.append((7.5, 8.5))
    outline.append((8.0, 9.5))
    outline.append((8.5, 8.0))
    outline += arc(6.0, 5.5, 3.0, 50, -30, 10)
    outline.append((9.5, 4.5))
    outline.append((11.5, 4.0))
    outline.append((9.5, 3.5))
    # Wattle as outline bump
    outline.append((9.0, 3.3))
    outline.append((9.5, 2.5))
    outline.append((9.0, 1.5))
    outline.append((8.5, 2.0))
    outline.append((8.5, 3.0))
    outline.append((9.0, 3.3))
    outline += arc(6.0, 5.5, 3.0, 330, 200, 12)
    outline.append((3.0, 6.5))
    outline.append((3.0, 8.0))
    features = [
        circle(7.0, 6.5, 0.3, 10),
    ]
    return outline, features, "Chicken head — jagged comb, beak, wattle, eye"


def chicken_candidate_3():
    outline: List[Point] = []
    outline.append((9.0, 7.0))
    outline.append((9.0, 7.8))
    outline.append((9.5, 7.0))
    outline.append((9.7, 7.8))
    outline.append((10.2, 7.0))
    outline.append((10.7, 6.5))
    outline.append((11.5, 6.0))
    outline.append((12.3, 5.6))
    outline.append((11.2, 5.3))
    outline.append((10.5, 4.5))
    outline += arc(6.0, 3.5, 4.5, -10, -180, 16)
    outline.append((2.0, 4.5))
    outline.append((2.5, 6.0))
    outline.append((4.0, 7.0))
    outline.append((6.0, 7.5))
    outline.append((8.0, 7.3))
    outline.append((9.0, 7.0))
    features = [
        # Eye
        [(10.7, 6.1), (10.7, 5.9), (10.5, 6.0)],
        # Wing loop
        [(5.0, 5.5), (7.0, 5.5), (6.0, 4.5)],
    ]
    return outline, features, "Sitting hen — egg-like body, small comb, wing loop"


def chicken_candidate_4():
    cx, cy, r = 5.0, 5.0, 4.0
    outline: List[Point] = []
    outline.append((cx, cy + r))
    outline += arc(cx, cy, r, 90, -45, 14)
    outline.append((cx + r + 0.2, cy - r * 0.3))
    outline.append((cx + r + 1.5, cy - r * 0.5))
    outline.append((cx + r + 0.2, cy - r * 0.7))
    outline += arc(cx, cy, r, -50, -130, 8)
    outline.append((cx - 0.5, cy - r))
    outline.append((cx - 0.5, cy - r - 1.0))
    outline.append((cx - 0.2, cy - r - 1.2))
    outline.append((cx - 0.2, cy - r))
    outline.append((cx + 0.5, cy - r))
    outline.append((cx + 0.5, cy - r - 1.0))
    outline.append((cx + 0.8, cy - r - 1.2))
    outline.append((cx + 0.8, cy - r))
    outline += arc(cx, cy, r, 220, 90, 14)
    features = [
        circle(cx + 2.0, cy + 0.5, 0.3, 10),
        # Wing
        [(cx - 1.5, cy - 1.0), (cx - 1.5, cy + 0.5), (cx, cy - 0.5)],
    ]
    return outline, features, "Round chick — full circle body, two legs, tiny wing"


def chicken_candidate_5():
    outline: List[Point] = []
    outline.append((10.5, 9.5))
    outline.append((11.5, 8.5))
    outline.append((10.5, 8.0))
    outline.append((11.0, 7.0))
    # Wattle as outline bump
    outline.append((11.5, 6.0))
    outline.append((10.5, 5.5))
    outline.append((10.0, 6.5))
    outline.append((10.5, 7.0))
    outline.append((11.0, 7.0))
    outline.append((9.5, 6.0))
    outline.append((8.5, 5.0))
    outline.append((8.5, 3.0))
    outline.append((9.0, 0.5))
    outline.append((9.5, 0.5))
    outline.append((9.5, 0.2))
    outline.append((10.0, 0.2))
    outline.append((10.0, 0.5))
    outline.append((10.5, 1.0))
    outline.append((10.0, 2.5))
    outline.append((6.0, 2.0))
    outline.append((5.0, 0.5))
    outline.append((4.5, 0.5))
    outline.append((4.5, 0.2))
    outline.append((4.0, 0.2))
    outline.append((4.0, 0.5))
    outline.append((3.5, 1.0))
    outline.append((4.0, 2.5))
    outline.append((2.5, 3.0))
    outline.append((1.5, 3.5))
    outline.append((0.5, 4.5))
    outline.append((0.0, 6.5))
    outline.append((1.0, 8.5))
    outline.append((1.5, 7.5))
    outline.append((2.0, 9.0))
    outline.append((2.5, 7.5))
    outline.append((3.0, 9.0))
    outline.append((3.5, 7.0))
    outline.append((4.0, 6.0))
    outline.append((5.0, 6.0))
    outline.append((6.5, 6.5))
    outline.append((7.5, 7.0))
    outline.append((8.0, 8.0))
    outline.append((8.5, 9.5))
    outline.append((9.0, 8.5))
    outline.append((9.5, 9.7))
    outline.append((10.0, 9.0))
    outline.append((10.5, 9.5))
    features = [
        [(9.2, 8.1), (9.2, 7.9), (9.0, 8.0)],
    ]
    return outline, features, "Crowing rooster — head back, open beak, dramatic plumes"


CANDIDATES = {
    "pig": [pig_candidate_2, pig_candidate_3, pig_candidate_4, pig_candidate_5],
    "cat": [cat_candidate_2, cat_candidate_3, cat_candidate_4, cat_candidate_5],
    "dog": [dog_candidate_2, dog_candidate_3, dog_candidate_4, dog_candidate_5],
    "dino": [dino_candidate_2, dino_candidate_3, dino_candidate_4, dino_candidate_5],
    "chicken": [
        chicken_candidate_2, chicken_candidate_3,
        chicken_candidate_4, chicken_candidate_5,
    ],
}


HEADER = '''"""{family} candidate {n} — {description}

Generated by `tools/gen_candidates.py`. Hand-crafted in Python pending
ingestion of source SVGs through `tools/svg_to_shape.py --with-interior`.

Format follows the standard shape-file interface (see `prototype/shapes.py`):
- OUTLINE: closed silhouette polyline.
- INTERIOR_FEATURES: list of polylines for interior detail strokes
  (whiskers, nostrils, eyes, etc.) — anchored to the outline at trace time
  by `compose_route()`.
- METADATA: free-form dict (description, source, license, …).
"""

from __future__ import annotations

from typing import List

from shape_utils import Point

OUTLINE: List[Point] = [
'''


def write_file(family: str, n: int, fn) -> Path:
    outline, features, description = fn()
    if outline[0] != outline[-1]:
        outline.append(outline[0])
    out_path = PROTO / f"{family}_candidate_{n}.py"
    body = HEADER.format(family=family.capitalize(), n=n, description=description)
    for x, y in outline:
        body += f"    ({x:.3f}, {y:.3f}),\n"
    body += "]\n\n"
    body += "INTERIOR_FEATURES: List[List[Point]] = [\n"
    for feat in features:
        body += "    [\n"
        for x, y in feat:
            body += f"        ({x:.3f}, {y:.3f}),\n"
        body += "    ],\n"
    body += "]\n\n"
    body += f'METADATA = {{"description": {description!r}, "source": "hand-crafted by tools/gen_candidates.py"}}\n'
    out_path.write_text(body)
    return out_path


def main() -> None:
    for family, fns in CANDIDATES.items():
        for i, fn in enumerate(fns, start=2):
            path = write_file(family, i, fn)
            print(f"wrote {path.relative_to(PROTO.parent)}")


if __name__ == "__main__":
    main()
