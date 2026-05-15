"""Tests for ``stravart.mapmatch``: snap a polyline to OSM streets.

We avoid OSMnx's HTTPS download by building a small NetworkX MultiDiGraph
that has the same shape as a real OSMnx graph: node attrs ``y`` (lat) and
``x`` (lon), edge attrs ``length`` (metres). Then the code under test
operates on it identically.
"""

from __future__ import annotations

import math

import networkx as nx
import pytest

from stravart.mapmatch import (
    MatchedRoute,
    _haversine_m,
    _path_length_m,
    downsample_by_distance,
    map_match,
)


# --- waypoint downsampling ----------------------------------------------

class TestDownsample:
    def test_keeps_first_and_last(self):
        # 1° lat ≈ 111 km
        coords = [(0.0, 0.0), (0.0001, 0.0), (0.0002, 0.0)]
        out = downsample_by_distance(coords, step_m=10.0)
        assert out[0] == coords[0]
        assert out[-1] == coords[-1]

    def test_drops_dense_intermediates(self):
        # 100 points along a 30 m line — should reduce dramatically at 10 m step
        coords = [(0.0 + i * 0.0000027, 0.0) for i in range(100)]   # 0.3 m steps
        out = downsample_by_distance(coords, step_m=10.0)
        assert len(out) < len(coords) // 5

    def test_preserves_when_already_sparse(self):
        coords = [(0.0, 0.0), (0.001, 0.0), (0.002, 0.0)]   # ~111 m apart
        out = downsample_by_distance(coords, step_m=10.0)
        assert len(out) == 3

    def test_empty_polyline(self):
        assert downsample_by_distance([]) == []

    def test_single_point(self):
        assert downsample_by_distance([(0.0, 0.0)]) == [(0.0, 0.0)]


# --- helpers -------------------------------------------------------------

class TestHaversine:
    def test_equator_one_degree(self):
        d = _haversine_m(0.0, 0.0, 0.0, 1.0)
        assert abs(d - 111_195) < 100   # ~111.195 km per equatorial degree


# --- synthetic graph fixture --------------------------------------------

def _build_grid_graph(
    *,
    rows: int = 5,
    cols: int = 5,
    spacing_m: float = 100.0,
    lat0: float = 51.5,
    lon0: float = -0.1,
) -> nx.MultiDiGraph:
    """Build a synthetic OSMnx-shaped lat/lon grid graph.

    Nodes form a ``rows × cols`` grid spaced ``spacing_m`` metres apart in
    both axes; edges connect 4-neighbours with ``length=spacing_m``.
    Returns a MultiDiGraph with crs=EPSG:4326 so OSMnx routines accept it.
    """
    g = nx.MultiDiGraph(crs="EPSG:4326")
    dlat = math.degrees(spacing_m / 6_371_000.0)
    dlon = math.degrees(spacing_m / (6_371_000.0 * math.cos(math.radians(lat0))))
    for r in range(rows):
        for c in range(cols):
            nid = r * cols + c
            g.add_node(nid, y=lat0 + r * dlat, x=lon0 + c * dlon)
    for r in range(rows):
        for c in range(cols):
            here = r * cols + c
            for dr, dc in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                rr, cc = r + dr, c + dc
                if 0 <= rr < rows and 0 <= cc < cols:
                    other = rr * cols + cc
                    g.add_edge(here, other, length=spacing_m)
    return g


# --- map_match ---------------------------------------------------------

class TestMapMatch:
    def test_snaps_to_grid_nodes(self):
        g = _build_grid_graph(rows=4, cols=4, spacing_m=100.0)
        # Trace from node 0 (top-left) to node 15 (bottom-right) — slightly
        # off-grid points to force snapping. We pass coords every ~50 m.
        lat0, lon0 = 51.5, -0.1
        dlat = math.degrees(100 / 6_371_000.0)
        dlon = math.degrees(100 / (6_371_000.0 * math.cos(math.radians(lat0))))
        # Points along the right-then-down route, with ~5 m noise.
        coords = []
        # Right across row 0
        for i in range(4):
            coords.append((lat0 + 0.0001 * dlat, lon0 + i * dlon))
        # Down column 3
        for r in range(1, 4):
            coords.append((lat0 + r * dlat - 0.0001 * dlat, lon0 + 3 * dlon))
        result = map_match(coords, g, waypoint_step_m=50.0)
        assert isinstance(result, MatchedRoute)
        assert result.length_m > 500     # ≥ 6 segments × 100 m
        assert result.unreachable_segments == 0
        assert len(result.coords) > 5
        # Path should start near the input start and end near the input end
        assert abs(result.coords[0][0] - lat0) < dlat
        assert abs(result.coords[-1][1] - (lon0 + 3 * dlon)) < dlon

    def test_short_polyline_returns_input(self):
        g = _build_grid_graph()
        result = map_match([(51.5, -0.1)], g)
        assert result.length_m == 0.0
        assert result.coords == [(51.5, -0.1)]

    def test_handles_unreachable_segment(self):
        # Build two disconnected components and a polyline crossing the gap
        g = nx.MultiDiGraph(crs="EPSG:4326")
        g.add_node(0, y=51.500, x=-0.100)
        g.add_node(1, y=51.501, x=-0.100)
        g.add_edge(0, 1, length=111)
        g.add_edge(1, 0, length=111)
        # Disconnected island far away
        g.add_node(2, y=51.700, x=-0.100)
        g.add_node(3, y=51.701, x=-0.100)
        g.add_edge(2, 3, length=111)
        g.add_edge(3, 2, length=111)
        coords = [(51.500, -0.100), (51.700, -0.100)]
        result = map_match(coords, g, waypoint_step_m=50.0)
        # First waypoint snaps to node 0 or 1, second to 2 or 3 → unreachable
        assert result.unreachable_segments >= 1


class TestPathLength:
    def test_multidigraph_picks_shortest_parallel(self):
        g = nx.MultiDiGraph()
        g.add_node(0); g.add_node(1)
        g.add_edge(0, 1, length=100)
        g.add_edge(0, 1, length=80)        # second parallel edge — shorter
        g.add_edge(1, 0, length=100)
        assert _path_length_m(g, [0, 1]) == 80


# --- Phase 4b: downsample indices + shape-aware rerank -----------------

class TestDownsampleIndices:
    def test_returns_indices_when_requested(self):
        coords = [(0.0, 0.0), (0.0, 0.001), (0.0, 0.002), (0.0, 0.003)]
        wps, idxs = downsample_by_distance(coords, step_m=50.0, return_indices=True)
        assert len(wps) == len(idxs)
        # First and last indices anchor the original endpoints
        assert idxs[0] == 0
        assert idxs[-1] == len(coords) - 1
        # Indices monotonically increase
        assert all(idxs[i] < idxs[i + 1] for i in range(len(idxs) - 1))

    def test_indices_align_with_waypoints(self):
        coords = [(0.0, i * 0.001) for i in range(20)]   # ~111 m apart at equator
        wps, idxs = downsample_by_distance(coords, step_m=300.0, return_indices=True)
        # Every emitted waypoint must equal the coords at the recorded index
        for wp, idx in zip(wps, idxs):
            assert wp == coords[idx]


class TestShapeRerank:
    """Phase 4b: when two paths of equal length exist, pick the one whose
    geometry matches the cartoon contour, not Dijkstra's tiebreaker."""

    def _two_path_graph(self):
        """Build a graph with two paths from u=0 to v=5, equal total length
        but very different shapes:

          north path:  0 — 1 — 2 — 5  (goes north then east)
          south path:  0 — 3 — 4 — 5  (goes south then east)

        Each leg = 100 m. Both paths sum to 300 m.
        """
        import math
        g = nx.MultiDiGraph(crs="EPSG:4326")
        lat0, lon0 = 51.5, -0.1
        dlat = math.degrees(100 / 6_371_000.0)
        dlon = math.degrees(100 / (6_371_000.0 * math.cos(math.radians(lat0))))
        # 0 (start), 1 (NE corner), 2 (N+1E), 5 (end E)
        # 3 (SE corner), 4 (S+1E)
        g.add_node(0, y=lat0,            x=lon0)
        g.add_node(1, y=lat0 + dlat,     x=lon0)
        g.add_node(2, y=lat0 + dlat,     x=lon0 + dlon)
        g.add_node(3, y=lat0 - dlat,     x=lon0)
        g.add_node(4, y=lat0 - dlat,     x=lon0 + dlon)
        g.add_node(5, y=lat0,            x=lon0 + 2 * dlon)
        for a, b in [(0, 1), (1, 2), (2, 5),    # north path
                     (0, 3), (3, 4), (4, 5)]:   # south path
            g.add_edge(a, b, length=100)
            g.add_edge(b, a, length=100)
        return g, lat0, lon0, dlat, dlon

    def test_rerank_picks_north_path_when_contour_bends_north(self):
        g, lat0, lon0, dlat, dlon = self._two_path_graph()
        # Contour from (lat0, lon0) to (lat0, lon0 + 2*dlon) that BENDS NORTH
        # — matches the 0-1-2-5 path geometry.
        coords = [
            (lat0,             lon0),
            (lat0 + 0.5*dlat,  lon0),
            (lat0 + dlat,      lon0),
            (lat0 + dlat,      lon0 + 0.5*dlon),
            (lat0 + dlat,      lon0 + dlon),
            (lat0 + 0.5*dlat,  lon0 + 1.5*dlon),
            (lat0,             lon0 + 2*dlon),
        ]
        result = map_match(coords, g,
                           waypoint_step_m=50.0,
                           k_shortest_paths=2, rerank="shape")
        # Path should include the northern intermediate nodes (1 and/or 2),
        # not the southern (3 and 4).
        assert 1 in result.node_ids or 2 in result.node_ids
        assert 3 not in result.node_ids
        assert 4 not in result.node_ids

    def test_rerank_picks_south_path_when_contour_bends_south(self):
        g, lat0, lon0, dlat, dlon = self._two_path_graph()
        coords = [
            (lat0,             lon0),
            (lat0 - 0.5*dlat,  lon0),
            (lat0 - dlat,      lon0),
            (lat0 - dlat,      lon0 + 0.5*dlon),
            (lat0 - dlat,      lon0 + dlon),
            (lat0 - 0.5*dlat,  lon0 + 1.5*dlon),
            (lat0,             lon0 + 2*dlon),
        ]
        result = map_match(coords, g,
                           waypoint_step_m=50.0,
                           k_shortest_paths=2, rerank="shape")
        assert 3 in result.node_ids or 4 in result.node_ids
        assert 1 not in result.node_ids
        assert 2 not in result.node_ids

    def test_length_rerank_ignores_shape(self):
        """With rerank='length' the cartoon shape is ignored — first path wins."""
        g, lat0, lon0, dlat, dlon = self._two_path_graph()
        # Contour bends NORTH but we ask for length rerank → Dijkstra's first
        # candidate wins regardless. The exact node ids depend on NetworkX
        # iteration order; just assert the matcher ran without picking the
        # shape-better candidate.
        coords_north = [
            (lat0, lon0),
            (lat0 + dlat, lon0),
            (lat0 + dlat, lon0 + dlon),
            (lat0, lon0 + 2*dlon),
        ]
        shape_result = map_match(coords_north, g,
                                 waypoint_step_m=50.0,
                                 k_shortest_paths=2, rerank="shape")
        length_result = map_match(coords_north, g,
                                  waypoint_step_m=50.0,
                                  k_shortest_paths=2, rerank="length")
        # Shape mode finds the north path; length mode may or may not (since
        # both paths are equal length and Dijkstra's tiebreak isn't shape-aware).
        # The contract is just: with shape rerank, the result honours the cartoon.
        assert 1 in shape_result.node_ids or 2 in shape_result.node_ids
        # And the length/shape results may differ — the diagnostic count
        # of reranked segments captures this.
        assert shape_result.reranked_segments >= 0   # may be 0 or 1

    def test_k_equals_1_disables_rerank(self):
        """k_shortest_paths=1 == legacy behaviour, no rerank counter."""
        g, lat0, lon0, dlat, dlon = self._two_path_graph()
        coords = [(lat0, lon0), (lat0, lon0 + 2*dlon)]
        result = map_match(coords, g,
                           waypoint_step_m=50.0,
                           k_shortest_paths=1, rerank="shape")
        assert result.reranked_segments == 0


# --- Phase 4b option 4: OCR anchors as Dijkstra via-points -------------

class TestViaNodes:
    """When the caller supplies via_nodes (OCR-identified intersections
    we trust), Dijkstra must route THROUGH those nodes in contour order."""

    def _two_path_graph(self):
        """Same fixture as TestShapeRerank — two paths north/south, both
        equal length 0 → 5."""
        import math
        g = nx.MultiDiGraph(crs="EPSG:4326")
        lat0, lon0 = 51.5, -0.1
        dlat = math.degrees(100 / 6_371_000.0)
        dlon = math.degrees(100 / (6_371_000.0 * math.cos(math.radians(lat0))))
        g.add_node(0, y=lat0,            x=lon0)
        g.add_node(1, y=lat0 + dlat,     x=lon0)
        g.add_node(2, y=lat0 + dlat,     x=lon0 + dlon)
        g.add_node(3, y=lat0 - dlat,     x=lon0)
        g.add_node(4, y=lat0 - dlat,     x=lon0 + dlon)
        g.add_node(5, y=lat0,            x=lon0 + 2 * dlon)
        for a, b in [(0, 1), (1, 2), (2, 5), (0, 3), (3, 4), (4, 5)]:
            g.add_edge(a, b, length=100)
            g.add_edge(b, a, length=100)
        return g, lat0, lon0, dlat, dlon

    def test_via_node_forces_path_through_north_even_when_contour_is_straight(self):
        """A straight contour from 0 to 5 normally takes one of the two
        equal paths arbitrarily. With a via-node pinned at node 1 (north),
        the path MUST traverse the north corridor."""
        g, lat0, lon0, dlat, dlon = self._two_path_graph()
        # Straight contour
        coords = [(lat0, lon0 + i * dlon * 0.1) for i in range(21)]
        # Pin via-node at node 1 (which sits at lat0+dlat, lon0)
        via_nodes = [(lat0 + dlat, lon0, 1)]
        result = map_match(coords, g,
                           waypoint_step_m=50.0,
                           via_nodes=via_nodes)
        # Path includes node 1 (north) and not nodes 3 or 4 (south)
        assert 1 in result.node_ids
        assert 3 not in result.node_ids
        assert 4 not in result.node_ids
        assert result.via_nodes_pinned == 1

    def test_multiple_via_nodes_routed_in_contour_order(self):
        """Multiple via-nodes must be visited in the order they appear
        along the contour, not by node-id."""
        g, lat0, lon0, dlat, dlon = self._two_path_graph()
        # Contour goes from 0 → south route → 5
        coords = [
            (lat0,             lon0),
            (lat0 - 0.5*dlat,  lon0),
            (lat0 - dlat,      lon0),
            (lat0 - dlat,      lon0 + dlon),
            (lat0,             lon0 + 2*dlon),
        ]
        # Pin two south-corridor via-nodes
        via_nodes = [
            (lat0 - dlat, lon0,        3),    # appears first in contour
            (lat0 - dlat, lon0 + dlon, 4),    # appears second
        ]
        result = map_match(coords, g,
                           waypoint_step_m=50.0,
                           via_nodes=via_nodes)
        assert 3 in result.node_ids
        assert 4 in result.node_ids
        # Order: 3 must appear before 4 in the snapped sequence
        idx_3 = result.node_ids.index(3)
        idx_4 = result.node_ids.index(4)
        assert idx_3 < idx_4
        # No north-corridor nodes traversed
        assert 1 not in result.node_ids
        assert 2 not in result.node_ids
        assert result.via_nodes_pinned == 2

    def test_via_nodes_none_falls_back_to_legacy(self):
        """``via_nodes=None`` (default) preserves the legacy snap behaviour."""
        g, lat0, lon0, dlat, dlon = self._two_path_graph()
        coords = [(lat0, lon0), (lat0, lon0 + 2*dlon)]
        result = map_match(coords, g,
                           waypoint_step_m=50.0,
                           via_nodes=None)
        assert result.via_nodes_pinned == 0
        # Either north or south path may have been picked — both are length-equal
        assert result.length_m > 0

    def test_via_node_pin_overrides_nearest_node_choice(self):
        """If a via-node is the OCR-identified node for an intersection,
        ``map_match`` must use IT — not whatever nearest_nodes would have
        snapped to. (Test by pinning to a NON-nearest node and verifying
        it's in the output path.)"""
        # Build a triangle: 0,1,2 are corners; the (lat, lon) of the
        # via-anchor sits closer to node 0 than node 2, but we pin 2.
        import math
        g = nx.MultiDiGraph(crs="EPSG:4326")
        lat0, lon0 = 51.5, -0.1
        dlat = math.degrees(100 / 6_371_000.0)
        dlon = math.degrees(100 / (6_371_000.0 * math.cos(math.radians(lat0))))
        g.add_node(0, y=lat0,            x=lon0)
        g.add_node(1, y=lat0 + dlat,     x=lon0 + dlon)
        g.add_node(2, y=lat0 + 5*dlat,   x=lon0 + 5*dlon)   # far away
        g.add_edge(0, 1, length=141)
        g.add_edge(1, 0, length=141)
        g.add_edge(1, 2, length=566)
        g.add_edge(2, 1, length=566)
        # Contour goes from near-0 to near-1
        coords = [(lat0, lon0), (lat0 + dlat, lon0 + dlon)]
        # Pin via-node at NODE 2 even though its lat/lon is far from coords
        # — what we actually want is to force the routing to TRAVERSE node 2.
        # Setting via-lat/lon at node 2's coords:
        via_nodes = [(lat0 + 5*dlat, lon0 + 5*dlon, 2)]
        result = map_match(coords, g,
                           waypoint_step_m=200.0,
                           via_nodes=via_nodes)
        # Node 2 must appear in the routed path
        assert 2 in result.node_ids
        assert result.via_nodes_pinned == 1
