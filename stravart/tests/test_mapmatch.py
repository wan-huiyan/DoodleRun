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
