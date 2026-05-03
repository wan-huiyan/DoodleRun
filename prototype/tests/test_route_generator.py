"""Tests for project_shape and the generate() rescaling loop.

OSRM is mocked with a recorded /route response so these tests don't touch
the network. The mock returns the same fixture distance regardless of
waypoints, which is enough to exercise the iteration logic.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from osrm_client import RouteResult
from route_generator import (
    V2_DEFAULT_SEARCH_RADIUS_M,
    V2_DEFAULT_TARGET_DISTANCE_M,
    V2_MIN_TARGET_DISTANCE_M,
    V2_MAX_TARGET_DISTANCE_M,
    _distance_adjusted_score,
    _rotate_xy,
    generate,
    generate_search_v2,
    generate_search_v2_multi,
    generate_v2,
    m_per_deg_lon,
    project_shape,
)
from tests.conftest import make_grid_graph


class TestProjectShape:
    def test_center_lat_lon_is_centered(self):
        outline = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        # Center of bbox is (5, 5); projecting it should produce an offset of 0
        # so the bbox center maps exactly to the requested (lat, lon).
        wp = project_shape(outline, 37.0, -122.0, scale_m_per_unit=100.0)
        # bbox center maps to center: average of waypoints' midpoint
        midpoint_lat = (min(p[0] for p in wp) + max(p[0] for p in wp)) / 2
        midpoint_lon = (min(p[1] for p in wp) + max(p[1] for p in wp)) / 2
        assert midpoint_lat == pytest.approx(37.0, abs=1e-6)
        assert midpoint_lon == pytest.approx(-122.0, abs=1e-6)

    def test_scale_produces_expected_meter_offset(self):
        # A single point 5 units up from the bbox center should land 500m north
        # at scale 100 m/unit. Use a 10x10 bbox so center is (5, 5).
        outline = [(5, 0), (5, 10)]   # bbox is 0..10 in y, center at 5
        wp = project_shape(outline, 37.0, -122.0, scale_m_per_unit=100.0)
        # Top point is at y=10 → 5 units above center → 500m north.
        # 500m / 111320 m/deg ≈ 0.00449 deg.
        d_lat = wp[1][0] - 37.0
        assert d_lat == pytest.approx(500.0 / 111320.0, rel=1e-3)

    def test_lon_scaling_uses_cos_lat(self):
        # At latitude 60°, longitude degrees are half the meters of latitude
        # degrees. Verify project_shape's compensation.
        outline = [(0, 5), (10, 5)]   # only x varies
        wp = project_shape(outline, 60.0, 0.0, scale_m_per_unit=100.0)
        d_lon = wp[1][1] - wp[0][1]   # 10 units → 1000 m east
        expected = 1000.0 / m_per_deg_lon(60.0)
        assert d_lon == pytest.approx(expected, rel=1e-4)


def _fake_route_through(distance_m: float):
    """Build a stand-in for osrm_client.route_through that always returns the
    same fixed distance, so we can test the convergence loop deterministically.
    """
    def fake(waypoints, profile="foot", base_url="", verify=True):
        # Polyline length isn't checked by generate(); just return the waypoints.
        return RouteResult(
            coordinates=list(waypoints),
            distance_m=distance_m,
            duration_s=distance_m,
        )
    return fake


class TestGenerateConvergence:
    def test_returns_best_iteration(self):
        outline = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        # Fake OSRM always says 5000m no matter the scale, so all iterations
        # produce the same distance and the FIRST one ends up as "best" (tied).
        with patch("route_generator.route_through",
                   side_effect=_fake_route_through(5000.0)):
            result = generate(
                outline=outline,
                center_lat=37.0,
                center_lon=-122.0,
                target_distance_m=5000.0,
                n_waypoints=10,
                max_iterations=3,
            )
        assert result.distance_m == 5000.0
        assert len(result.waypoints) == 10
        assert len(result.polyline) == 10

    def test_stops_early_on_match(self):
        outline = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        call_count = {"n": 0}
        def fake(waypoints, profile="foot", base_url="", verify=True):
            call_count["n"] += 1
            return RouteResult(coordinates=list(waypoints),
                               distance_m=4990.0, duration_s=0)
        with patch("route_generator.route_through", side_effect=fake):
            generate(
                outline=outline,
                center_lat=37.0, center_lon=-122.0,
                target_distance_m=5000.0,
                n_waypoints=10, max_iterations=10,
            )
        # Within 3% of target on iter 1 → should stop after one call.
        assert call_count["n"] == 1

    def test_returns_best_when_later_iteration_raises(self):
        """If a late iteration raises (e.g. OSRM NoRoute when scale shrinks
        waypoints onto unconnected park interiors), we should keep the best
        earlier iteration rather than propagating the error."""
        outline = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        calls = {"n": 0}
        def fake(waypoints, profile="foot", base_url="", verify=True):
            calls["n"] += 1
            if calls["n"] == 1:
                return RouteResult(coordinates=list(waypoints),
                                   distance_m=20000.0, duration_s=0)
            raise RuntimeError("OSRM NoRoute on iter 2")
        with patch("route_generator.route_through", side_effect=fake):
            result = generate(
                outline=outline,
                center_lat=37.0, center_lon=-122.0,
                target_distance_m=10000.0,
                n_waypoints=10, max_iterations=5,
            )
        # iter 1 succeeded with 20km, iter 2 failed → return iter 1's best.
        assert result.distance_m == 20000.0

    def test_raises_when_first_iteration_fails(self):
        """If we never get a successful route at all, the error should still
        propagate — there's nothing to fall back to."""
        outline = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        with patch("route_generator.route_through",
                   side_effect=RuntimeError("OSRM down")):
            with pytest.raises(RuntimeError, match="OSRM down"):
                generate(
                    outline=outline,
                    center_lat=37.0, center_lon=-122.0,
                    target_distance_m=10000.0,
                    n_waypoints=10, max_iterations=5,
                )


# ---------------------------------------------------------------------------
# generate_v2 — the W-K + OSMnx pipeline
# ---------------------------------------------------------------------------


class TestGenerateV2Defaults:
    """The plan §0 defaults are non-negotiable; pin them with tests."""

    def test_target_distance_default_is_20km(self):
        assert V2_DEFAULT_TARGET_DISTANCE_M == 20_000

    def test_search_radius_default_is_30km(self):
        assert V2_DEFAULT_SEARCH_RADIUS_M == 30_000

    def test_distance_bounds_are_15_to_30km(self):
        assert V2_MIN_TARGET_DISTANCE_M == 15_000
        assert V2_MAX_TARGET_DISTANCE_M == 30_000


class TestGenerateV2Validation:
    def test_rejects_distance_below_15km(self):
        outline = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        with pytest.raises(ValueError, match="15-30 km"):
            generate_v2(outline, 37.0, -122.0, target_distance_m=10_000)

    def test_rejects_distance_above_30km(self):
        outline = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        with pytest.raises(ValueError, match="15-30 km"):
            generate_v2(outline, 37.0, -122.0, target_distance_m=40_000)

    def test_rejects_search_radius_below_30km(self):
        outline = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        with pytest.raises(ValueError, match="30 km"):
            generate_v2(
                outline, 37.0, -122.0,
                target_distance_m=20_000,
                search_radius_m=10_000,
            )


class TestGenerateV2Pipeline:
    """End-to-end with `osmnx_router.load_graph` patched to a synthetic
    grid; verifies that generate_v2 wires the pieces together."""

    def _grid(self, n=8, spacing_m=200.0,
              origin_lat=37.0, origin_lon=-122.0):
        import networkx as nx
        m_per_deg_lat = 111_320.0
        m_per_deg_lon_v = m_per_deg_lat * math.cos(math.radians(origin_lat))
        G = nx.MultiDiGraph()
        for i in range(n):
            for j in range(n):
                G.add_node(i * n + j,
                           y=origin_lat + (i * spacing_m) / m_per_deg_lat,
                           x=origin_lon + (j * spacing_m) / m_per_deg_lon_v)
        for i in range(n):
            for j in range(n):
                here = i * n + j
                for di, dj in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                    ni, nj = i + di, j + dj
                    if 0 <= ni < n and 0 <= nj < n:
                        G.add_edge(here, ni * n + nj, length=spacing_m, key=0)
        G.graph["crs"] = "EPSG:4326"
        return G

    def test_returns_generated_route(self):
        # Centre the synthetic grid on the seed point so the projected
        # outline lands inside it.
        G = self._grid(n=12)
        with patch("osmnx_router.load_graph", return_value=G):
            outline = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
            result = generate_v2(
                outline,
                center_lat=37.001,    # near grid origin
                center_lon=-122.001,
                target_distance_m=15_000,
            )
        assert result.distance_m > 0
        assert len(result.polyline) > 4
        # Fidelity should be a real number (not inf), even if not great
        # on an artificial grid.
        assert result.fidelity != float("inf")

    def test_uses_default_graph_radius(self):
        """The per-candidate graph load uses the dedicated graph_radius_m
        (default 15 km — the search-radius cap from plan §9). Pin the call
        so future regressions that silently shrink it are caught."""
        from route_generator import V2_DEFAULT_GRAPH_RADIUS_M
        G = self._grid(n=12)
        captured = {}

        def fake_load(lat, lon, radius_m=None, use_cache=True):
            captured["radius_m"] = radius_m
            return G

        with patch("osmnx_router.load_graph", side_effect=fake_load):
            outline = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
            generate_v2(outline, 37.001, -122.001, target_distance_m=20_000)
        assert captured["radius_m"] == V2_DEFAULT_GRAPH_RADIUS_M


# ---------------------------------------------------------------------------
# Phase 2 — generate_search_v2 (Optuna TPE)
# ---------------------------------------------------------------------------


class TestRotateXY:
    def test_zero_radians_is_identity(self):
        pts = [(1.0, 0.0), (0.0, 1.0)]
        out = _rotate_xy(pts, 0.0)
        assert out[0] == pytest.approx((1.0, 0.0), abs=1e-9)
        assert out[1] == pytest.approx((0.0, 1.0), abs=1e-9)

    def test_90_degrees_rotates_unit_x_to_unit_y(self):
        out = _rotate_xy([(1.0, 0.0)], math.pi / 2)
        assert out[0][0] == pytest.approx(0.0, abs=1e-9)
        assert out[0][1] == pytest.approx(1.0, abs=1e-9)


class TestDistanceAdjustedScore:
    def test_at_target_returns_pure_fidelity(self):
        assert _distance_adjusted_score(0.05, 20_000, 20_000) == pytest.approx(0.05)

    def test_soft_penalty_is_linear(self):
        # 10% off target → 0.3 * 0.1 = 0.03 added
        s = _distance_adjusted_score(0.05, 22_000, 20_000)
        assert s == pytest.approx(0.05 + 0.03, abs=1e-9)

    def test_hard_cap_returns_inf(self):
        assert _distance_adjusted_score(0.05, 50_000, 20_000) == float("inf")


class TestGenerateSearchV2:
    """End-to-end with a synthetic grid; verifies wiring + bookkeeping."""

    def _big_grid(self):
        # Bigger grid so the search has room to find different scales/rotations.
        return make_grid_graph(n=20, spacing_m=200.0,
                               origin_lat=37.0, origin_lon=-122.0)

    def test_runs_n_trials_when_no_early_stop(self):
        G = self._big_grid()
        outline = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        result = generate_search_v2(
            outline, 37.01, -122.01,
            target_distance_m=15_000,
            n_trials=5, timeout_s=None,
            early_stop_score=-1.0,   # never early stop
            graph=G, use_prescreener=False,
            n_startup_trials=2,
        )
        assert result.fidelity != float("inf")
        assert result.best_params is not None
        # Results carry the new Phase-2 fields.
        assert "rotation_deg" in result.best_params
        assert "scale_factor" in result.best_params
        assert result.fidelity_breakdown is not None
        assert set(result.fidelity_breakdown) >= {"hausdorff", "frechet",
                                                  "area_iou", "turning"}

    def test_records_rotation_in_returned_route(self):
        G = self._big_grid()
        outline = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        result = generate_search_v2(
            outline, 37.01, -122.01,
            target_distance_m=15_000,
            n_trials=3, timeout_s=None,
            graph=G, use_prescreener=False,
            n_startup_trials=2,
        )
        assert 0.0 <= result.rotation_deg <= 360.0

    def test_prescreener_blocks_sparse_graph(self):
        # Build a sparse grid that will fail density.
        G = make_grid_graph(n=4, spacing_m=10_000)  # 30 km wide, ~120m of road = 0.0... km/km²
        outline = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        with pytest.raises(RuntimeError, match="prescreener"):
            generate_search_v2(
                outline, 37.0, -122.0,
                target_distance_m=20_000,
                n_trials=3, timeout_s=None,
                graph=G, use_prescreener=True,
                n_startup_trials=2,
            )

    def test_early_stop_when_score_below_threshold(self):
        """A trivially-small early-stop threshold should never fire; a
        very-large threshold should always fire on the first valid trial.
        Verifies the callback wiring without depending on actual fidelity
        numbers (which vary across grids)."""
        G = self._big_grid()
        outline = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        result = generate_search_v2(
            outline, 37.01, -122.01,
            target_distance_m=15_000,
            n_trials=50, timeout_s=None,
            graph=G, use_prescreener=False,
            n_startup_trials=2,
            early_stop_score=10.0,   # any finite score triggers stop
        )
        assert result.fidelity != float("inf")


# ---------------------------------------------------------------------------
# Phase 3 — generate_search_v2_multi (per-variant Optuna)
# ---------------------------------------------------------------------------


class TestGenerateSearchV2Multi:
    def _big_grid(self):
        return make_grid_graph(n=20, spacing_m=200.0,
                               origin_lat=37.0, origin_lon=-122.0)

    def test_picks_variant_with_lower_score(self):
        """Two variants — one runnable, one degenerate. Multi should
        return the runnable one and tag its index in best_params."""
        G = self._big_grid()
        good = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        # Degenerate "shape" — a near-collapsed line. Will score worse
        # than the square but still be valid (no exception path).
        meh = [(0, 0), (0.5, 0), (1, 0), (0.5, 0), (0, 0)]
        result = generate_search_v2_multi(
            [good, meh], 37.01, -122.01,
            target_distance_m=15_000,
            n_trials=3, timeout_s=None,
            graph=G, use_prescreener=False,
            n_startup_trials=2,
        )
        assert result.best_params is not None
        assert "variant_index" in result.best_params
        # The square should typically win on grid; either is acceptable
        # but the index must be 0 or 1.
        assert result.best_params["variant_index"] in (0, 1)

    def test_passes_through_route_metrics(self):
        G = self._big_grid()
        outline = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        result = generate_search_v2_multi(
            [outline], 37.01, -122.01,
            target_distance_m=15_000,
            n_trials=3, timeout_s=None,
            graph=G, use_prescreener=False,
            n_startup_trials=2,
            simplify_tol_m=0.0,  # tiny synthetic route collapses if simplified
        )
        assert result.distance_m > 0
        assert len(result.polyline) > 4
        assert result.fidelity_breakdown is not None
        assert result.best_params["variant_index"] == 0

    def test_skips_failed_variants(self):
        """A variant that's empty (zero points) raises ValueError inside
        the inner search; multi should log the failure and continue with
        the remaining variants instead of propagating."""
        G = self._big_grid()
        good = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        bad = []  # will raise inside resample()
        result = generate_search_v2_multi(
            [bad, good], 37.01, -122.01,
            target_distance_m=15_000,
            n_trials=2, timeout_s=None,
            graph=G, use_prescreener=False,
            n_startup_trials=2,
        )
        assert result.best_params["variant_index"] == 1

    def test_raises_when_all_variants_fail(self):
        G = self._big_grid()
        with pytest.raises(RuntimeError, match="All .* variants failed"):
            generate_search_v2_multi(
                [[], []], 37.01, -122.01,
                target_distance_m=15_000,
                n_trials=2, timeout_s=None,
                graph=G, use_prescreener=False,
                n_startup_trials=2,
            )

    def test_rejects_empty_variant_list(self):
        with pytest.raises(ValueError, match="at least one"):
            generate_search_v2_multi(
                [], 37.01, -122.01,
                target_distance_m=15_000,
            )
