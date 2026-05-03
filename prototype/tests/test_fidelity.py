"""Tests for fidelity.py — geometric correctness of haversine, densify,
and the symmetric mean-min distance score."""

from __future__ import annotations

import math

import pytest

from fidelity import (
    DEFAULT_WEIGHTS,
    area_iou_score,
    bbox_diagonal_m,
    combined_score,
    densify,
    fidelity_score,
    frechet_score,
    haversine,
)


class TestHaversine:
    def test_zero_distance(self):
        assert haversine((51.5, -0.1), (51.5, -0.1)) == pytest.approx(0.0, abs=1e-6)

    def test_one_degree_latitude_is_about_111km(self):
        d = haversine((51.0, 0.0), (52.0, 0.0))
        # 1° lat ≈ 111.32 km regardless of longitude.
        assert d == pytest.approx(111_000.0, abs=2_000.0)

    def test_one_degree_longitude_at_equator_is_about_111km(self):
        d = haversine((0.0, 0.0), (0.0, 1.0))
        assert d == pytest.approx(111_000.0, abs=2_000.0)

    def test_one_degree_longitude_at_60_lat_is_about_55km(self):
        # cos(60°) = 0.5 → 1° lon ≈ 55.7 km
        d = haversine((60.0, 0.0), (60.0, 1.0))
        assert d == pytest.approx(55_700.0, abs=2_000.0)


class TestBboxDiagonal:
    def test_empty(self):
        assert bbox_diagonal_m([]) == 0.0

    def test_single_point(self):
        assert bbox_diagonal_m([(51.5, -0.1)]) == 0.0

    def test_finds_corner_to_corner(self):
        # 1° × 1° square (huge but easy to reason about).
        d = bbox_diagonal_m([(51.0, -1.0), (52.0, -1.0),
                             (51.0,  0.0), (52.0,  0.0)])
        # 1° lat ≈ 111 km; 1° lon at 51.5° ≈ 69 km; diag ≈ √(111² + 69²) ≈ 130km.
        assert 120_000 < d < 145_000


class TestDensify:
    def test_short_segment_passes_through(self):
        line = [(51.5, -0.1), (51.5001, -0.1001)]
        out = densify(line, step_m=100)
        assert out == line   # all gaps <= 100m, nothing inserted

    def test_inserts_intermediates(self):
        # 1° lat ≈ 111km; with step_m=10000, expect ~11 intermediates.
        line = [(51.0, 0.0), (52.0, 0.0)]
        out = densify(line, step_m=10_000)
        assert len(out) >= 11
        assert out[0] == (51.0, 0.0)
        assert out[-1] == (52.0, 0.0)

    def test_zero_step_returns_original(self):
        line = [(0, 0), (1, 1)]
        assert densify(line, step_m=0) == line


class TestFidelityScore:
    def test_perfect_tracing_scores_zero(self):
        ideal = [(51.5, -0.1), (51.501, -0.099), (51.502, -0.098)]
        # Snapped IS the ideal — should score 0.
        score = fidelity_score(ideal, ideal)
        assert score == pytest.approx(0.0, abs=1e-6)

    def test_higher_deviation_scores_worse(self):
        ideal = [(51.500, -0.100), (51.500, -0.090), (51.500, -0.080)]
        # Snapped runs 100m to the north of the ideal everywhere.
        offset_lat = 100 / 111_320.0
        snap = [(p[0] + offset_lat, p[1]) for p in ideal]
        score_close = fidelity_score(ideal, snap)
        # Snapped runs 500m to the north — should score ~5x worse.
        offset_lat_far = 500 / 111_320.0
        snap_far = [(p[0] + offset_lat_far, p[1]) for p in ideal]
        score_far = fidelity_score(ideal, snap_far)
        assert score_far > score_close
        assert score_far / score_close == pytest.approx(5.0, abs=0.5)

    def test_score_uses_first_arg_for_normalization(self):
        """The fidelity score is symmetric in the mean-min averaging but NOT
        in the bbox diagonal used for normalisation — the first argument is
        treated as the *target* shape. Document the asymmetry so callers
        always pass the idealized outline first.
        """
        a = [(51.5, -0.1), (51.51, -0.09)]   # smaller bbox
        b = [(51.5, -0.1), (51.6, 0.0)]       # bigger bbox
        s_ab = fidelity_score(a, b)
        s_ba = fidelity_score(b, a)
        assert s_ab != s_ba

    def test_empty_inputs_return_inf(self):
        assert fidelity_score([], [(51.5, -0.1)]) == float("inf")
        assert fidelity_score([(51.5, -0.1)], []) == float("inf")

    def test_score_normalised_by_bbox(self):
        """Sanity check: a 100 m offset is catastrophic on a 500 m shape but
        modest on a 5 km shape. The scale-normalised score should reflect
        that — the small case must score much worse than the big one."""
        # Small target: ~500 m line (lat span 0.0045°)
        small_ideal = [(51.500, -0.10), (51.5045, -0.10)]
        # 100m offset (≈ 0.0009° lat).
        small_snap = [(p[0] + 0.0009, p[1]) for p in small_ideal]
        # Big target: ~5km line, same 100m offset
        big_ideal = [(51.500, -0.10), (51.545, -0.10)]
        big_snap = [(p[0] + 0.0009, p[1]) for p in big_ideal]
        s_small = fidelity_score(small_ideal, small_snap)
        s_big = fidelity_score(big_ideal, big_snap)
        # Same absolute deviation, 10x larger bbox → score ~10x lower.
        assert s_big < s_small / 5


class TestFrechet:
    def test_perfect_tracing_scores_zero(self):
        ideal = [(51.5, -0.1), (51.501, -0.099), (51.502, -0.098)]
        assert frechet_score(ideal, ideal) == pytest.approx(0.0, abs=1e-6)

    def test_offset_polyline_scores_positive(self):
        ideal = [(51.500, -0.10), (51.500, -0.09)]
        offset_lat = 50 / 111_320.0
        snap = [(p[0] + offset_lat, p[1]) for p in ideal]
        assert frechet_score(ideal, snap) > 0

    def test_empty_inputs_return_inf(self):
        assert frechet_score([], [(51.5, -0.1)]) == float("inf")


class TestAreaIoU:
    def test_identical_polylines_score_zero(self):
        ideal = [(51.5, -0.1), (51.501, -0.099), (51.502, -0.098)]
        assert area_iou_score(ideal, ideal, buffer_m=20) == pytest.approx(0.0, abs=1e-6)

    def test_disjoint_polylines_score_one(self):
        a = [(51.500, -0.100), (51.500, -0.099)]      # near London
        b = [(40.700, -74.000), (40.701, -74.000)]    # NYC — buffers can't overlap
        assert area_iou_score(a, b, buffer_m=20) == pytest.approx(1.0, abs=1e-3)

    def test_in_unit_interval(self):
        ideal = [(51.500, -0.100), (51.500, -0.090), (51.510, -0.090)]
        offset_lat = 60 / 111_320.0
        snap = [(p[0] + offset_lat, p[1]) for p in ideal]
        s = area_iou_score(ideal, snap, buffer_m=50)
        assert 0.0 < s < 1.0


class TestCombinedScore:
    def test_perfect_tracing_scores_zero(self):
        ideal = [(51.500, -0.100), (51.500, -0.090), (51.510, -0.090),
                 (51.510, -0.100), (51.500, -0.100)]
        assert combined_score(ideal, ideal) == pytest.approx(0.0, abs=1e-6)

    def test_breakdown_matches_constituents(self):
        ideal = [(51.500, -0.100), (51.500, -0.090), (51.510, -0.090)]
        offset_lat = 80 / 111_320.0
        snap = [(p[0] + offset_lat, p[1]) for p in ideal]
        score, br = combined_score(ideal, snap, return_breakdown=True)
        # Breakdown holds the three current constituents and the weights.
        assert set(br) == {"hausdorff", "frechet", "area_iou", "weights"}
        # Recomputing the weighted sum lines up with the returned score.
        recomputed = (br["weights"]["hausdorff"] * br["hausdorff"]
                      + br["weights"]["frechet"] * br["frechet"]
                      + br["weights"]["area_iou"] * br["area_iou"])
        assert score == pytest.approx(recomputed, rel=1e-9)

    def test_default_weights_sum_to_known_total(self):
        # Phase 1 totals 0.85; turning-function bumps to 1.0 in Phase 2.
        # If anyone changes the weights, this test forces them to update
        # the plan and the docstring at the same time.
        total = sum(DEFAULT_WEIGHTS.values())
        assert total == pytest.approx(0.85, abs=1e-6)
        assert DEFAULT_WEIGHTS["turning"] == 0.0
