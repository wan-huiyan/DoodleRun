"""Tests for the in-tree turning_function module.

We re-derive the canonical Arkin et al. (1991) properties from a few
pure-geometry inputs:
  - identical polygons score 0
  - rotation invariance: a rotated copy still scores ~0 after the
    closed-form θ optimisation
  - scale invariance: doubling all coordinates leaves the score unchanged
  - a square vs. a triangle scores noticeably positive
  - empty / degenerate inputs return the saturation value (1.0 normalised)
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from turning_function import (
    DEFAULT_MAX_POINTS,
    _resample_uniform,
    _turning_function,
    turning_distance,
)


def _square(side: float = 1.0):
    return [(0, 0), (side, 0), (side, side), (0, side)]


def _triangle(side: float = 1.0):
    return [(0, 0), (side, 0), (side / 2, side * math.sqrt(3) / 2)]


def _rotate(points, theta: float):
    c, s = math.cos(theta), math.sin(theta)
    return [(x * c - y * s, x * s + y * c) for x, y in points]


class TestTurningFunction:
    def test_square_turning_function_sums_to_2pi(self):
        # A simple convex polygon traversed CCW turns by exactly 2π in
        # one full loop.
        s, theta = _turning_function(np.asarray(_square()), closed=True)
        # Last value of theta should equal cumulative turning of the
        # closing vertex BEFORE it wraps the loop — for the closed
        # square that's three 90° turns at the interior vertices = 3π/2.
        # The closing edge adds the final 90° to make 2π, but we don't
        # surface it as a vertex.
        assert theta[-1] == pytest.approx(3 * math.pi / 2, abs=1e-6)

    def test_resample_keeps_endpoints(self):
        pts = np.asarray([(0, 0), (1, 0), (1, 1), (0, 1)], dtype=float)
        out = _resample_uniform(pts, 10)
        assert out[0] == pytest.approx(pts[0])
        assert out[-1] == pytest.approx(pts[-1])
        assert len(out) == 10


class TestTurningDistance:
    def test_identical_polygons_score_zero(self):
        sq = _square()
        assert turning_distance(sq, sq, closed=True) == pytest.approx(0.0, abs=1e-9)

    def test_rotation_invariance(self):
        # The closed-form θ optimisation should completely cancel a
        # global rotation — score must remain ~0.
        sq = _square()
        rotated = _rotate(sq, math.radians(37))
        d = turning_distance(sq, rotated, closed=True)
        assert d == pytest.approx(0.0, abs=1e-6)

    def test_scale_invariance(self):
        # Multiplying all coordinates by 2 changes nothing about turning.
        sq1 = _square(1.0)
        sq2 = _square(2.0)
        d = turning_distance(sq1, sq2, closed=True)
        assert d == pytest.approx(0.0, abs=1e-9)

    def test_square_vs_triangle_is_positive(self):
        d = turning_distance(_square(), _triangle(), closed=True)
        assert d > 0.05  # clearly different polygons

    def test_normalised_in_unit_interval(self):
        # Even pathological pair stays clamped to [0, 1].
        weird = [(0, 0), (1, 0), (0, 1), (1, 1)]  # crossing polygon
        d = turning_distance(_square(), weird, closed=True)
        assert 0.0 <= d <= 1.0

    def test_empty_inputs(self):
        assert turning_distance([], [(0, 0), (1, 0), (0, 1)]) == pytest.approx(1.0)
        assert turning_distance([(0, 0)], [(0, 0)]) == pytest.approx(1.0)

    def test_phase_shift_helps_when_polygons_have_different_starts(self):
        # Same polygon, different starting vertex — without phase shift
        # the score is non-zero; with phase shift it should drop.
        sq = _square()
        shifted = sq[2:] + sq[:2]
        no_shift = turning_distance(sq, shifted, closed=True, n_phase_shifts=0)
        with_shift = turning_distance(sq, shifted, closed=True, n_phase_shifts=4)
        assert with_shift <= no_shift
        assert with_shift == pytest.approx(0.0, abs=1e-6)

    def test_max_points_resamples_long_inputs(self):
        # 500-point spiral, should not blow up despite > DEFAULT_MAX_POINTS.
        n = 500
        ts = np.linspace(0, 2 * math.pi, n)
        spiral = [(math.cos(t) * (1 + 0.05 * t), math.sin(t) * (1 + 0.05 * t))
                  for t in ts]
        d = turning_distance(spiral, spiral, closed=False, max_points=DEFAULT_MAX_POINTS)
        assert d == pytest.approx(0.0, abs=1e-3)
