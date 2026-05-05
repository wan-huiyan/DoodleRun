"""Tests for ``stravart.fidelity_score``: Fréchet + buffered-IoU shape comparison."""

from __future__ import annotations

import math

import pytest

from stravart.fidelity_score import (
    buffered_iou,
    discrete_frechet_m,
    fidelity,
)


# ----------------------------------------------------- discrete Fréchet

class TestDiscreteFrechet:
    def test_identical_polylines_score_zero(self):
        line = [(51.5, -0.1), (51.51, -0.1), (51.51, -0.09)]
        assert discrete_frechet_m(line, line) < 0.5

    def test_parallel_offset(self):
        # Two parallel horizontal polylines, ~111 m apart in latitude
        a = [(51.5, -0.1), (51.5, -0.09)]
        b = [(51.501, -0.1), (51.501, -0.09)]
        d = discrete_frechet_m(a, b)
        assert 100 < d < 130

    def test_disjoint_inputs(self):
        a = [(51.5, -0.1), (51.51, -0.1)]
        b = [(40.7, -74.0), (40.71, -74.0)]      # NYC vs London
        d = discrete_frechet_m(a, b)
        assert d > 5_000_000      # ~5500 km

    def test_empty_input_returns_inf(self):
        assert math.isinf(discrete_frechet_m([], [(0.0, 0.0)]))


# ------------------------------------------------------ buffered IoU

class TestBufferedIou:
    def test_identical_polylines_iou_is_one(self):
        line = [(51.5, -0.1), (51.5, -0.09)]
        assert buffered_iou(line, line, buffer_m=20.0) == pytest.approx(1.0)

    def test_disjoint_polylines_score_zero(self):
        a = [(51.5, -0.1), (51.51, -0.1)]
        b = [(40.7, -74.0), (40.71, -74.0)]
        assert buffered_iou(a, b, buffer_m=20.0) == 0.0

    def test_partial_overlap_score_between_zero_and_one(self):
        # Two horizontal lines at the same lat but with 50% length overlap.
        a = [(51.5, -0.1), (51.5, -0.0980)]   # ~140 m long
        b = [(51.5, -0.0990), (51.5, -0.0970)]   # ~140 m long, half-overlapping
        iou = buffered_iou(a, b, buffer_m=20.0)
        assert 0.05 < iou < 0.95

    def test_negative_buffer_raises(self):
        line = [(51.5, -0.1), (51.5, -0.09)]
        with pytest.raises(ValueError):
            buffered_iou(line, line, buffer_m=-5.0)

    def test_empty_input(self):
        line = [(51.5, -0.1), (51.5, -0.09)]
        assert buffered_iou([], line, buffer_m=20.0) == 0.0


# ---------------------------------------------------------- combined

class TestFidelity:
    def test_identical_inputs_pass(self):
        line = [(51.5, -0.1), (51.5, -0.09), (51.51, -0.09)]
        f = fidelity(line, line)
        assert f.passes
        assert f.score == pytest.approx(1.0, abs=0.01)
        assert f.buffered_iou == pytest.approx(1.0)
        assert f.frechet_m < 0.5

    def test_offset_polylines_score_lower(self):
        a = [(51.5, -0.1), (51.5, -0.09)]
        b = [(51.501, -0.1), (51.501, -0.09)]
        f = fidelity(a, b, buffer_m=20.0)
        # ~111 m offset, buffer 20 m → IoU should be small
        assert f.score < 0.6
        assert not f.passes

    def test_disjoint_inputs_fail(self):
        a = [(51.5, -0.1), (51.5, -0.09)]
        b = [(40.7, -74.0), (40.71, -74.0)]
        f = fidelity(a, b)
        assert f.score == 0.0
        assert not f.passes
