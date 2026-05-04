"""Tests for grid_prescreener.py.

All tests run against the synthetic NetworkX grid from conftest —
zero live OSM calls. Real-graph behaviour is exercised by `smoke_v2.py`
during integration runs.
"""

from __future__ import annotations

import math
import random

import networkx as nx
import pytest

from grid_prescreener import (
    DEFAULT_MIN_DENSITY_KM,
    grid_regularity,
    is_connected,
    prescreen,
    road_density_km,
    _approx_area_km2,
)
from tests.conftest import make_grid_graph


class TestRoadDensity:
    def test_dense_grid_clears_default_threshold(self, grid_graph_factory):
        # 5×5 grid, 100m spacing → 4×5×2 = 40 edges × 100 m = 4 km of road
        # in a 0.4×0.4 = 0.16 km² area → 25 km/km² (way above 5).
        G = grid_graph_factory()
        assert road_density_km(G) > DEFAULT_MIN_DENSITY_KM

    def test_sparse_grid_fails_threshold(self, grid_graph_factory):
        # Same 5×5 layout but spacing 5km → 25 km × 25 km area, still 4 km
        # of road → 0.0064 km/km², well under threshold.
        G = grid_graph_factory(spacing_m=5_000)
        assert road_density_km(G) < DEFAULT_MIN_DENSITY_KM

    def test_empty_graph_returns_zero(self):
        G = nx.MultiDiGraph()
        G.graph["crs"] = "EPSG:4326"
        assert road_density_km(G) == 0.0


class TestGridRegularity:
    def test_perfect_grid_scores_below_random(self, grid_graph_factory):
        """A perfect 4-direction grid uses 4 of 36 bearing bins, so the
        Shannon entropy floor is log(4)/log(36) ≈ 0.39 — not zero. The
        useful invariant is that this is *much* lower than a network with
        scattered bearings (random reaches close to 1).
        """
        G_grid = grid_graph_factory()
        random.seed(0)
        G_chaos = grid_graph_factory(n=10)
        node_ids = list(G_chaos.nodes)
        for _ in range(80):
            u = random.choice(node_ids)
            new_id = max(node_ids) + 1
            G_chaos.add_node(new_id,
                             y=37.0 + random.uniform(0, 0.05),
                             x=-122.0 + random.uniform(0, 0.05))
            node_ids.append(new_id)
            G_chaos.add_edge(u, new_id, length=random.uniform(10, 200), key=0)

        grid_score = grid_regularity(G_grid)
        chaos_score = grid_regularity(G_chaos)

        # Sanity bounds: both in [0, 1], grid measurably lower than chaos.
        assert 0.0 <= grid_score <= 1.0
        assert 0.0 <= chaos_score <= 1.0
        assert grid_score < chaos_score - 0.1

    def test_perfect_grid_in_expected_low_band(self, grid_graph_factory):
        # log(4)/log(36) = 0.387; should be well below the entropy of any
        # truly disorderly network (which sits near 0.9+).
        score = grid_regularity(grid_graph_factory())
        assert score < 0.5


class TestIsConnected:
    def test_full_grid_is_connected(self, grid_graph_factory):
        assert is_connected(grid_graph_factory()) is True

    def test_isolated_node_below_threshold(self, grid_graph_factory):
        # 5×5=25 nodes; add 12 isolated nodes → largest CC = 25/(25+12) ≈ 0.68
        # → fails the 0.7 threshold.
        G = grid_graph_factory()
        for k in range(12):
            G.add_node(100 + k, y=38.0 + k * 0.0001, x=-123.0)
        assert is_connected(G, min_fraction=0.7) is False
        # But succeeds at a relaxed threshold.
        assert is_connected(G, min_fraction=0.5) is True

    def test_empty_graph_returns_false(self):
        G = nx.MultiDiGraph()
        G.graph["crs"] = "EPSG:4326"
        assert is_connected(G) is False


class TestPrescreen:
    def test_pass_on_dense_connected_grid(self, grid_graph_factory):
        ok, info = prescreen(grid_graph_factory())
        assert ok is True
        assert info["rejected_for"] is None

    def test_reject_for_density(self, grid_graph_factory):
        ok, info = prescreen(grid_graph_factory(spacing_m=5_000))
        assert ok is False
        assert info["rejected_for"] == "density"

    def test_reject_for_connectivity(self, grid_graph_factory):
        G = grid_graph_factory()
        for k in range(20):
            G.add_node(200 + k, y=39.0 + k * 0.0001, x=-124.0)
        ok, info = prescreen(G)
        assert ok is False
        assert info["rejected_for"] == "connectivity"


def test_approx_area_km2_matches_bbox(grid_graph_factory):
    G = grid_graph_factory(n=5, spacing_m=100)
    # 5x5 grid with 100m spacing → 0.4 × 0.4 = 0.16 km².
    a = _approx_area_km2(G)
    assert a == pytest.approx(0.16, rel=0.05)
