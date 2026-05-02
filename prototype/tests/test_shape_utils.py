"""Tests for shape_utils.resample / outline_perimeter / bounding_box."""

from __future__ import annotations

import math

import pytest

from shape_utils import bounding_box, outline_perimeter, resample


class TestOutlinePerimeter:
    def test_unit_square(self):
        square = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        assert outline_perimeter(square) == pytest.approx(4.0)

    def test_diagonal(self):
        diag = [(0, 0), (3, 4)]
        assert outline_perimeter(diag) == pytest.approx(5.0)

    def test_single_point(self):
        assert outline_perimeter([(1, 1)]) == 0.0

    def test_zero_length_segments(self):
        same = [(0, 0), (0, 0), (0, 0)]
        assert outline_perimeter(same) == 0.0


class TestResample:
    def test_count(self):
        triangle = [(0, 0), (1, 0), (0.5, 1), (0, 0)]
        out = resample(triangle, 12)
        assert len(out) == 12

    def test_endpoints_preserved(self):
        line = [(0, 0), (10, 0)]
        out = resample(line, 5)
        assert out[0] == (0, 0)
        assert out[-1] == (10, 0)

    def test_evenly_spaced_on_straight_line(self):
        line = [(0, 0), (10, 0)]
        out = resample(line, 11)
        for i, (x, y) in enumerate(out):
            assert x == pytest.approx(i)
            assert y == pytest.approx(0)

    def test_perimeter_preserved_within_tolerance(self):
        circle_approx = [
            (math.cos(t), math.sin(t))
            for t in [i * math.pi / 8 for i in range(17)]
        ]
        original_p = outline_perimeter(circle_approx)
        out = resample(circle_approx, 50)
        # Resampling along the polyline cannot increase length and only
        # smooths over kinks; should be within 1% on a smooth curve.
        assert outline_perimeter(out) == pytest.approx(original_p, rel=0.01)

    def test_n_too_small_raises(self):
        with pytest.raises(ValueError):
            resample([(0, 0), (1, 1)], 1)

    def test_zero_length_input_returns_repeated_point(self):
        out = resample([(2, 3), (2, 3)], 5)
        assert out == [(2, 3)] * 5


class TestBoundingBox:
    def test_simple(self):
        assert bounding_box([(0, 0), (5, 3), (-2, 4)]) == (-2, 0, 5, 4)

    def test_single_point(self):
        assert bounding_box([(7, 9)]) == (7, 9, 7, 9)


class TestActualShapes:
    """Sanity checks on the bundled animal outlines."""

    @pytest.mark.parametrize("shape_name", ["pig", "cat", "dog", "dino", "chicken"])
    def test_shape_is_closed_loop(self, shape_name):
        from shapes import SHAPES
        outline = SHAPES[shape_name]
        # A closed outline starts and ends at the same point.
        assert outline[0] == outline[-1], f"{shape_name} outline does not close"

    @pytest.mark.parametrize("shape_name", ["pig", "cat", "dog", "dino", "chicken"])
    def test_shape_has_enough_points(self, shape_name):
        from shapes import SHAPES
        # Need at least ~30 points for any animal silhouette to resolve.
        assert len(SHAPES[shape_name]) >= 30
