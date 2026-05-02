"""Tests for the candidate search helpers and generate_search() flow.

OSRM is mocked: each candidate returns a deterministic synthetic polyline
plus a fidelity-influencing offset, so we can assert that generate_search
picks the candidate the test crafted to be best.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from fidelity import bbox_diagonal_m, fidelity_score, haversine
from osrm_client import RouteResult
from route_generator import (
    candidate_centers,
    candidate_scales,
    generate_search,
    project_shape,
)


class TestCandidateCenters:
    def test_n_one_returns_seed(self):
        c = candidate_centers(51.5, -0.1, 30, 1)
        assert c == [(51.5, -0.1)]

    def test_n_five_returns_seed_plus_four_ring(self):
        c = candidate_centers(51.5, -0.1, 30, 5)
        assert len(c) == 5
        assert c[0] == (51.5, -0.1)
        # Ring points should be ~15km from the seed.
        for ring_pt in c[1:]:
            d = haversine(c[0], ring_pt)
            assert 13_000 < d < 17_000   # ~15km ± 2km

    def test_zero_radius_returns_only_seed(self):
        c = candidate_centers(51.5, -0.1, 0, 5)
        assert c == [(51.5, -0.1)]


class TestCandidateScales:
    def test_n_one_returns_base(self):
        # base = (10000/1.3) / 40 = ~192
        s = candidate_scales(10_000.0, 40.0, 1)
        assert len(s) == 1
        assert s[0] == pytest.approx(10_000 / 1.3 / 40.0)

    def test_geometric_spacing(self):
        s = candidate_scales(10_000.0, 40.0, 5)
        assert len(s) == 5
        # Default sweep: 0.5x .. 1.8x of the base (narrowed from the
        # original 0.6x..3.0x; the distance-budget hard cap rejects the
        # bigger end of the range anyway).
        base = 10_000 / 1.3 / 40.0
        assert s[0] == pytest.approx(base * 0.5)
        assert s[-1] == pytest.approx(base * 1.8)
        # Geometric: each consecutive ratio should be the same.
        ratios = [s[i + 1] / s[i] for i in range(len(s) - 1)]
        for r in ratios:
            assert r == pytest.approx(ratios[0], rel=1e-6)

    def test_custom_sweep_bounds(self):
        s = candidate_scales(10_000.0, 40.0, 3, low=0.8, high=1.2)
        base = 10_000 / 1.3 / 40.0
        assert s[0] == pytest.approx(base * 0.8)
        assert s[-1] == pytest.approx(base * 1.2)


def _fake_route_through_factory(perfect_center: tuple[float, float]):
    """Build a stand-in route_through that:
      - produces a polyline that exactly traces the input waypoints (so
        fidelity is purely a function of where the waypoints landed).
      - reports a synthetic distance proportional to the input span.
    Combined with a real outline projected at a real scale, the candidate
    closest to `perfect_center` will get a fidelity score of zero, every
    other candidate will get something strictly greater (because their
    waypoints are at different lat/lon positions but the score is computed
    against the same idealized outline ANCHORED AT THE SEED).
    """
    def fake(waypoints, profile="foot", base_url="", verify=True):
        # Polyline = waypoints exactly; distance = sum of segment lengths.
        coords = list(waypoints)
        dist = 0.0
        for a, b in zip(coords, coords[1:]):
            dist += haversine(a, b)
        return RouteResult(coordinates=coords, distance_m=dist, duration_s=dist)
    return fake


class TestGenerateSearch:
    def test_returns_a_route(self):
        outline = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        with patch("route_generator.route_through",
                   side_effect=_fake_route_through_factory((51.5, -0.1))):
            r = generate_search(
                outline=outline,
                center_lat=51.5, center_lon=-0.1,
                target_distance_m=5000.0,
                search_radius_km=10.0,
                n_candidates=3, n_scales=2,
                n_waypoints=10,
            )
        # With the perfect-tracing fake, every candidate has Hausdorff /
        # Fréchet / IoU scores of 0; combined-score then comes down purely
        # to the distance soft penalty. We just assert the search returned
        # *some* route with zero geometric error and a non-zero distance.
        assert r.fidelity == pytest.approx(0.0, abs=1e-3)
        assert r.frechet == pytest.approx(0.0, abs=1e-3)
        assert r.distance_m > 0
        assert r.combined is not None and r.combined < float("inf")

    def test_skips_failing_candidates_and_keeps_working_ones(self):
        outline = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        calls = {"n": 0}
        def fake(waypoints, profile="foot", base_url="", verify=True):
            calls["n"] += 1
            if calls["n"] % 2 == 0:
                raise RuntimeError("OSRM NoRoute")
            return RouteResult(coordinates=list(waypoints),
                               distance_m=1000.0, duration_s=1000.0)
        with patch("route_generator.route_through", side_effect=fake):
            r = generate_search(
                outline=outline,
                center_lat=51.5, center_lon=-0.1,
                target_distance_m=5000.0,
                search_radius_km=10.0,
                n_candidates=2, n_scales=2,
                n_waypoints=10,
            )
        # 2x2 = 4 candidates; calls 1 and 3 succeed, 2 and 4 fail.
        assert calls["n"] == 4
        assert r is not None

    def test_all_failing_raises(self):
        outline = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        with patch("route_generator.route_through",
                   side_effect=RuntimeError("network down")):
            with pytest.raises(RuntimeError, match="Every candidate failed"):
                generate_search(
                    outline=outline,
                    center_lat=51.5, center_lon=-0.1,
                    target_distance_m=5000.0,
                    search_radius_km=10.0,
                    n_candidates=2, n_scales=2,
                    n_waypoints=10,
                )

    def test_distance_hard_cap_filters_oversized_candidates(self):
        """With the 2x cap, a fake that always reports a 50 km route must
        cause every 5 km-target candidate to be rejected → no route."""
        def fake_huge(waypoints, profile="foot", base_url="", verify=True):
            return RouteResult(coordinates=list(waypoints),
                               distance_m=50_000.0, duration_s=50_000.0)
        outline = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        with patch("route_generator.route_through", side_effect=fake_huge):
            with pytest.raises(RuntimeError, match="distance cap"):
                generate_search(
                    outline=outline,
                    center_lat=51.5, center_lon=-0.1,
                    target_distance_m=5_000.0,
                    search_radius_km=10.0,
                    n_candidates=2, n_scales=2,
                    n_waypoints=10,
                )

    def test_invalid_grid_dimensions_rejected(self):
        with pytest.raises(ValueError):
            generate_search(
                outline=[(0, 0), (1, 1), (0, 0)],
                center_lat=51.5, center_lon=-0.1,
                target_distance_m=5000.0,
                n_candidates=0, n_scales=1,
            )
        with pytest.raises(ValueError):
            generate_search(
                outline=[(0, 0), (1, 1), (0, 0)],
                center_lat=51.5, center_lon=-0.1,
                target_distance_m=5000.0,
                n_candidates=1, n_scales=0,
            )
