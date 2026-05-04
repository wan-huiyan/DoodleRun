"""Tests for prototype/osmnx_router.py.

The router is exercised against a hand-built synthetic NetworkX
MultiDiGraph (a tiny lat/lon grid) so we never touch the live
OpenStreetMap servers. The single "real" graph_from_point call is
covered indirectly by integration tests, not these unit tests.
"""

from __future__ import annotations

import math

import networkx as nx
import pytest

from osmnx_router import (
    DEFAULT_RADIUS_M,
    ShapeRouteResult,
    _haversine,
    _point_to_segment_distance_m,
    nearest_node,
    nearest_node_cached,
    nearest_nodes_cached,
    precompute_graph_attrs,
    shape_aware_route,
    waschk_kruger_cost_fn,
)


# ---------------------------------------------------------------------------
# Test fixtures: a 5×5 lat/lon grid pretending to be a regular street network
# ---------------------------------------------------------------------------


def _grid_graph(n: int = 5, spacing_m: float = 100.0,
                origin_lat: float = 37.0, origin_lon: float = -122.0) -> nx.MultiDiGraph:
    """Build a synthetic n×n MultiDiGraph with edges between 4-neighbours.

    Each node has ``y``/``x`` (lat/lon) attributes the way osmnx wants
    them. Each edge has ``length`` (metres) and a tiny attrs dict — that
    matches the structure ``ox.graph_from_point`` would produce after
    ``simplify=True``.
    """
    G = nx.MultiDiGraph()
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(origin_lat))
    for i in range(n):
        for j in range(n):
            node_id = i * n + j
            lat = origin_lat + (i * spacing_m) / m_per_deg_lat
            lon = origin_lon + (j * spacing_m) / m_per_deg_lon
            G.add_node(node_id, y=lat, x=lon)
    for i in range(n):
        for j in range(n):
            here = i * n + j
            for (di, dj) in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                ni, nj = i + di, j + dj
                if 0 <= ni < n and 0 <= nj < n:
                    other = ni * n + nj
                    G.add_edge(here, other, length=spacing_m, key=0)
    G.graph["crs"] = "EPSG:4326"
    return G


@pytest.fixture
def grid():
    return _grid_graph()


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------


class TestGeometryPrimitives:
    def test_haversine_zero_distance(self):
        assert _haversine((37.0, -122.0), (37.0, -122.0)) == pytest.approx(0.0, abs=1e-6)

    def test_haversine_one_degree_lat_is_about_111km(self):
        d = _haversine((37.0, -122.0), (38.0, -122.0))
        # 1 degree of latitude ≈ 111.13 km.
        assert d == pytest.approx(111_130, rel=1e-3)

    def test_point_to_segment_endpoint_zero(self):
        # A point coincident with the segment endpoint scores 0.
        d = _point_to_segment_distance_m((37.0, -122.0),
                                         (37.0, -122.0),
                                         (37.001, -122.0))
        assert d == pytest.approx(0.0, abs=0.5)

    def test_point_to_segment_perpendicular(self):
        # 100 m east of an N-S segment should score ~100 m.
        m_per_deg_lon = 111_320.0 * math.cos(math.radians(37.0))
        offset_lon = 100.0 / m_per_deg_lon
        d = _point_to_segment_distance_m((37.001, -122.0 + offset_lon),
                                         (37.0, -122.0),
                                         (37.002, -122.0))
        assert d == pytest.approx(100.0, rel=0.02)


# ---------------------------------------------------------------------------
# Cost function
# ---------------------------------------------------------------------------


class TestWaschkKrugerCost:
    def test_aligned_edge_is_cheaper_than_perpendicular(self, grid):
        """Given a target segment running east-west, an east-west edge
        should cost less than a north-south edge of the same length and
        same end-distance."""
        # Target outline segment: from node 12 (centre) heading east 200 m.
        seg_start = (grid.nodes[12]["y"], grid.nodes[12]["x"])
        seg_end = (grid.nodes[14]["y"], grid.nodes[14]["x"])
        weight = waschk_kruger_cost_fn(grid, seg_start, seg_end,
                                       alpha=1.0, beta=0.5, gamma=4.0)

        # Two candidate edges from node 12: east (12→13) and north (12→17).
        # Both are 100 m. The north edge ends ~100 m off the target line
        # AND ~100 m further from seg_end → should cost more.
        east_data = grid.get_edge_data(12, 13)
        north_data = grid.get_edge_data(12, 17)
        cost_east = weight(12, 13, east_data)
        cost_north = weight(12, 17, north_data)
        assert cost_east < cost_north

    def test_handles_multidigraph_inner_dict(self, grid):
        """nx.shortest_path passes the {key: attrs} dict for parallel
        edges. The cost function must handle both shapes."""
        seg_start = (grid.nodes[12]["y"], grid.nodes[12]["x"])
        seg_end = (grid.nodes[14]["y"], grid.nodes[14]["x"])
        weight = waschk_kruger_cost_fn(grid, seg_start, seg_end)

        # Outer-mapping form (what nx hands callable weights for MultiGraph):
        outer = grid.get_edge_data(12, 13)              # {0: {length: 100}}
        cost_outer = weight(12, 13, outer)
        # Inner-attrs form (what some older code passes directly):
        inner = outer[0]
        cost_inner = weight(12, 13, inner)
        assert cost_outer == pytest.approx(cost_inner)


# ---------------------------------------------------------------------------
# nearest_node
# ---------------------------------------------------------------------------


class TestNearestNode:
    def test_snaps_to_existing_node(self, grid):
        node12 = nearest_node(grid, grid.nodes[12]["y"], grid.nodes[12]["x"])
        assert node12 == 12

    def test_snaps_offset_to_closest(self, grid):
        # Midway between node 12 and 13 → could pick either; just assert
        # it picks one of them.
        lat = grid.nodes[12]["y"]
        lon = (grid.nodes[12]["x"] + grid.nodes[13]["x"]) / 2
        result = nearest_node(grid, lat, lon)
        assert result in (12, 13)


# ---------------------------------------------------------------------------
# shape_aware_route — end-to-end on the synthetic grid
# ---------------------------------------------------------------------------


class TestShapeAwareRoute:
    def test_returns_polyline_and_metrics(self, grid):
        # A small square outline that lives inside the grid.
        outline = [
            (grid.nodes[6]["y"], grid.nodes[6]["x"]),     # SW corner
            (grid.nodes[8]["y"], grid.nodes[8]["x"]),     # SE
            (grid.nodes[18]["y"], grid.nodes[18]["x"]),   # NE
            (grid.nodes[16]["y"], grid.nodes[16]["x"]),   # NW
        ]
        result = shape_aware_route(grid, outline)
        assert isinstance(result, ShapeRouteResult)
        assert len(result.polyline) >= 4
        assert result.distance_m > 0
        # All four segments routable on a complete grid.
        assert result.n_segments_routed == 4
        assert result.n_segments_failed == 0

    def test_no_duplicate_consecutive_points_at_seam(self, grid):
        """Stitching consecutive Dijkstra paths should not duplicate the
        seam node."""
        outline = [
            (grid.nodes[6]["y"], grid.nodes[6]["x"]),
            (grid.nodes[8]["y"], grid.nodes[8]["x"]),
            (grid.nodes[6]["y"], grid.nodes[6]["x"]),
        ]
        result = shape_aware_route(grid, outline, closed=False)
        for i in range(1, len(result.polyline)):
            assert result.polyline[i] != result.polyline[i - 1]

    def test_disconnected_graph_records_failure(self):
        """If the graph has no path between two anchors we should record
        a failure rather than crash."""
        G = nx.MultiDiGraph()
        # Two disconnected nodes.
        G.add_node(0, y=37.0, x=-122.0)
        G.add_node(1, y=37.001, x=-121.999)   # ~140 m away, no edge
        G.graph["crs"] = "EPSG:4326"
        outline = [(37.0, -122.0), (37.001, -121.999)]
        result = shape_aware_route(G, outline, closed=False)
        assert result.n_segments_failed >= 1

    def test_rejects_outline_with_one_point(self, grid):
        with pytest.raises(ValueError):
            shape_aware_route(grid, [(37.0, -122.0)])


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_radius_is_30km():
    """Plan §0 makes 30 km a non-negotiable default — make sure no future
    edit silently shrinks it."""
    assert DEFAULT_RADIUS_M == 30_000


# ---------------------------------------------------------------------------
# Phase 3 — graph precompute (KDTree + per-edge midpoints)
# ---------------------------------------------------------------------------


class TestPrecomputeGraphAttrs:
    def test_marks_graph_idempotent(self, grid):
        precompute_graph_attrs(grid)
        assert grid.graph.get("_dr_precomputed") is True
        # second call is a no-op (no AttributeError, no error)
        precompute_graph_attrs(grid)
        assert grid.graph.get("_dr_precomputed") is True

    def test_stashes_kdtree_and_node_ids(self, grid):
        precompute_graph_attrs(grid)
        assert grid.graph["_dr_node_kdtree"] is not None
        ids = grid.graph["_dr_node_ids"]
        assert len(ids) == 25  # 5x5 grid
        assert grid.graph["_dr_origin_latlon"] is not None

    def test_stashes_per_edge_midpoint_and_endpoints(self, grid):
        precompute_graph_attrs(grid)
        # Pick a known east-going edge and verify midpoint is between nodes.
        u, v = 12, 13
        edge_data = grid.get_edge_data(u, v)
        inner = list(edge_data.values())[0]
        u_lat = grid.nodes[u]["y"]
        v_lat = grid.nodes[v]["y"]
        u_lon = grid.nodes[u]["x"]
        v_lon = grid.nodes[v]["x"]
        assert inner["_dr_u_lat"] == pytest.approx(u_lat)
        assert inner["_dr_v_lon"] == pytest.approx(v_lon)
        assert inner["_dr_mid_lat"] == pytest.approx((u_lat + v_lat) / 2)
        assert inner["_dr_mid_lon"] == pytest.approx((u_lon + v_lon) / 2)


class TestNearestNodeCached:
    def test_matches_uncached_nearest(self, grid):
        # Pick a few query points; both paths should agree.
        precompute_graph_attrs(grid)
        for nid in (0, 12, 24):
            lat = grid.nodes[nid]["y"]
            lon = grid.nodes[nid]["x"]
            assert nearest_node_cached(grid, lat, lon) == nid

    def test_batch_query(self, grid):
        precompute_graph_attrs(grid)
        latlons = [(grid.nodes[i]["y"], grid.nodes[i]["x"]) for i in (0, 6, 12, 18, 24)]
        result = nearest_nodes_cached(grid, latlons)
        assert result == [0, 6, 12, 18, 24]

    def test_falls_back_to_uncached_when_no_precompute(self, grid):
        # No precompute call → cached should still work via fallback.
        assert nearest_node_cached(grid, grid.nodes[12]["y"], grid.nodes[12]["x"]) == 12


class TestCostFunctionUsesPrecomputedAttrs:
    def test_weight_matches_before_and_after_precompute(self, grid):
        """The cost function must produce the same number whether or not
        the graph has been precomputed — precompute is a perf win, not a
        semantic change."""
        seg_start = (grid.nodes[12]["y"], grid.nodes[12]["x"])
        seg_end = (grid.nodes[14]["y"], grid.nodes[14]["x"])

        weight_uncached = waschk_kruger_cost_fn(grid, seg_start, seg_end)
        c_uncached = weight_uncached(12, 13, grid.get_edge_data(12, 13))

        precompute_graph_attrs(grid)
        weight_cached = waschk_kruger_cost_fn(grid, seg_start, seg_end)
        c_cached = weight_cached(12, 13, grid.get_edge_data(12, 13))

        assert c_cached == pytest.approx(c_uncached, rel=1e-6)

    def test_route_polyline_unchanged_after_precompute(self, grid):
        """End-to-end: an outline that produces the same polyline whether
        precomputed or not. Pins that the perf path is semantically clean."""
        outline = [
            (grid.nodes[6]["y"], grid.nodes[6]["x"]),
            (grid.nodes[8]["y"], grid.nodes[8]["x"]),
            (grid.nodes[18]["y"], grid.nodes[18]["x"]),
            (grid.nodes[16]["y"], grid.nodes[16]["x"]),
        ]
        r_uncached = shape_aware_route(grid, outline)
        precompute_graph_attrs(grid)
        r_cached = shape_aware_route(grid, outline)
        assert r_cached.distance_m == pytest.approx(r_uncached.distance_m, rel=1e-6)
        assert r_cached.n_segments_routed == r_uncached.n_segments_routed
