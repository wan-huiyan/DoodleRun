"""Tests for the route-contour pipeline (HSV mask → skeleton → polyline).

Synthesised fixtures: we draw coloured strokes on a desaturated grey field
with cv2 primitives, then assert the pipeline recovers the same shape.
No network, no real images — runs in <1s.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from stravart.contour import (
    RouteContour,
    clean_mask,
    extract_route,
    route_mask_colored,
    skeleton_of,
    trace_route,
)


# --- Fixtures ------------------------------------------------------------

def _grey_basemap(h: int = 200, w: int = 200, value: int = 200) -> np.ndarray:
    """Desaturated background (BGR uint8) — looks like a Carto basemap."""
    return np.full((h, w, 3), value, dtype=np.uint8)


def _stroke(canvas: np.ndarray, points, *, color=(0, 0, 230), thickness=4) -> np.ndarray:
    """Draw a polyline stroke onto ``canvas`` and return it."""
    pts = np.asarray(points, dtype=np.int32).reshape(-1, 1, 2)
    cv2.polylines(canvas, [pts], isClosed=False, color=color, thickness=thickness)
    return canvas


# --- HSV mask -----------------------------------------------------------

class TestRouteMaskColored:
    def test_picks_up_red_stroke(self):
        bg = _grey_basemap()
        # bright red
        img = _stroke(bg, [(10, 100), (190, 100)], color=(0, 0, 230), thickness=5)
        mask = route_mask_colored(img)
        assert mask.dtype == np.uint8
        assert mask.shape == img.shape[:2]
        # most of the stroke should be on
        assert mask[100, 50] == 255
        assert mask[100, 150] == 255
        # background untouched
        assert mask[0, 0] == 0

    def test_picks_up_magenta_stroke(self):
        bg = _grey_basemap()
        img = _stroke(bg, [(10, 50), (190, 50)], color=(180, 0, 200), thickness=5)
        mask = route_mask_colored(img)
        assert mask[50, 100] == 255

    def test_ignores_desaturated_basemap(self):
        bg = _grey_basemap(value=180)   # uniform mid-grey
        mask = route_mask_colored(bg)
        assert not mask.any()

    def test_rejects_non_bgr_input(self):
        with pytest.raises(ValueError):
            route_mask_colored(np.zeros((10, 10), dtype=np.uint8))


# --- Cleaning -----------------------------------------------------------

class TestCleanMask:
    def test_keeps_largest_blob(self):
        m = np.zeros((100, 100), dtype=np.uint8)
        # tiny blob at (5,5) — should be dropped
        cv2.rectangle(m, (3, 3), (7, 7), 255, -1)
        # big blob across middle
        cv2.rectangle(m, (20, 40), (80, 60), 255, -1)
        cleaned = clean_mask(m, min_area=50)
        # tiny blob gone
        assert cleaned[5, 5] == 0
        # big blob still there
        assert cleaned[50, 50] == 255

    def test_returns_empty_when_below_min_area(self):
        m = np.zeros((100, 100), dtype=np.uint8)
        cv2.rectangle(m, (10, 10), (15, 15), 255, -1)
        cleaned = clean_mask(m, min_area=10_000)
        assert not cleaned.any()


# --- Skeleton + trace --------------------------------------------------

class TestSkeleton:
    def test_skeleton_is_one_pixel_wide(self):
        m = np.zeros((100, 100), dtype=np.uint8)
        cv2.rectangle(m, (40, 40), (60, 60), 255, -1)  # 21x21 filled square
        skel = skeleton_of(m)
        # skeleton of a filled rectangle should have << area
        assert skel.sum() < m.sum() // 5

    def test_empty_mask_returns_empty_skeleton(self):
        m = np.zeros((50, 50), dtype=np.uint8)
        skel = skeleton_of(m)
        assert not skel.any()


class TestTraceRoute:
    def test_traces_horizontal_line(self):
        skel = np.zeros((50, 100), dtype=np.uint8)
        skel[25, 10:90] = 1
        path = trace_route(skel)
        assert len(path) == 80
        # endpoints are at (10, 25) and (89, 25); start at one, end at other
        xs = [p[0] for p in path]
        assert min(xs) == 10
        assert max(xs) == 89
        # x values are monotone (a clean line)
        assert xs == sorted(xs) or xs == sorted(xs, reverse=True)

    def test_traces_l_shape(self):
        skel = np.zeros((100, 100), dtype=np.uint8)
        skel[50, 10:50] = 1   # horizontal arm
        skel[50:90, 50] = 1   # vertical arm
        path = trace_route(skel)
        # path should cover both arms — 40 horizontal + 40 vertical = ~80 px
        assert len(path) >= 75
        # ends at one of the two endpoints
        ends = {(10, 50), (50, 89)}
        assert path[0] in ends and path[-1] in ends

    def test_handles_closed_loop(self):
        skel = np.zeros((100, 100), dtype=np.uint8)
        # Approximate a circle
        cv2.circle(skel, (50, 50), 30, 1, thickness=1)
        path = trace_route(skel)
        # circle perimeter ≈ 2π·30 ≈ 188 — skeletonised may differ a bit
        assert len(path) > 100

    def test_empty_skeleton_returns_empty_polyline(self):
        skel = np.zeros((50, 50), dtype=np.uint8)
        assert trace_route(skel) == []


# --- End-to-end --------------------------------------------------------

class TestExtractRoute:
    def test_recovers_polyline_from_red_stroke_on_grey(self):
        bg = _grey_basemap(300, 300)
        # diagonal stroke from (50, 50) to (250, 250)
        img = _stroke(
            bg, [(50, 50), (150, 100), (250, 250)],
            color=(0, 0, 220), thickness=5,
        )
        result = extract_route(img)
        assert isinstance(result, RouteContour)
        assert len(result.polyline) > 50
        # Polyline starts/ends near the stroke endpoints (within 5px tolerance —
        # skeletonisation pulls in slightly).
        start, end = result.polyline[0], result.polyline[-1]
        endpoints = {(50, 50), (250, 250)}
        ok = lambda p: any(abs(p[0]-e[0]) + abs(p[1]-e[1]) <= 6 for e in endpoints)
        assert ok(start)
        assert ok(end)
        # length_px is the polyline arc length, not zero
        assert result.length_px > 100

    def test_returns_empty_polyline_on_blank_basemap(self):
        bg = _grey_basemap()
        result = extract_route(bg)
        assert result.polyline == []
        assert result.length_px == 0.0

    def test_drops_distance_marker_pin_alongside_stroke(self):
        bg = _grey_basemap(300, 300)
        # The stroke
        _stroke(bg, [(20, 150), (280, 150)], color=(0, 0, 220), thickness=5)
        # A small distance-marker pin (red dot, size << stroke length)
        cv2.circle(bg, (260, 30), 6, (0, 0, 220), -1)
        result = extract_route(bg)
        # pin should be filtered out by largest-component filter
        ys = [y for _, y in result.polyline]
        assert max(ys) < 60 or all(y > 100 for y in ys), \
            "pin near (260, 30) should not appear in the traced polyline"
