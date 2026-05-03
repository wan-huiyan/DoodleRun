"""Shape-aware routing on a local OSMnx walking graph.

Replaces the OSRM HTTP path. Loads a NetworkX MultiDiGraph for an area
once, caches it to disk, then runs a *segment-by-segment* Dijkstra in
which the per-edge cost penalises edges that deviate from the current
target outline segment. This is the Waschk & Krüger (2019) C₃ idea on
top of OSMnx primitives — the only piece we own is the cost function;
everything else (download, parse, snap, Dijkstra) is library code.

Key design choices:

- **Default radius is 30 km** for graph extraction. Smaller has been
  shown empirically to leave too little room for the shape to fit.
- **Default target distance is 20 km** (callers should pass 15-30 km).
- The cost function combines three terms (Waschk & Krüger eq. 4):
  C₁ = haversine(v, segment_end)        — progress toward the goal
  C₂ = edge length                       — discourages U-turns / detours
  C₃ = perpendicular distance from the   — keeps us on roads that
        edge midpoint to the target        run alongside the outline
        segment line                       (the critical innovation)
- Disk cache: GraphML at ``graph_cache/<lat>_<lon>_<r>.graphml``.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

import networkx as nx
import osmnx as ox

LatLon = Tuple[float, float]

# 30 km is non-negotiable; see plan §0.
DEFAULT_RADIUS_M = 30_000

CACHE_DIR = Path(__file__).resolve().parent / "graph_cache"
CACHE_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Geometry helpers (small enough to inline, but unit-tested)
# ---------------------------------------------------------------------------

EARTH_R_M = 6_371_008.8


def _haversine(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in metres (same formula as fidelity.py — kept
    local so this module has no cross-module dep on fidelity)."""
    lat1, lon1 = a
    lat2, lon2 = b
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(h))


def _point_to_segment_distance_m(p: LatLon, a: LatLon, b: LatLon) -> float:
    """Approximate distance (metres) from point p to segment a→b.

    Operates in a small local-tangent plane around p. For city-scale
    distances (<5 km) this is accurate to <0.1%, which is far below the
    routing noise we're trying to score against.
    """
    lat0 = math.radians((a[0] + b[0]) / 2)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = m_per_deg_lat * math.cos(lat0)

    px = (p[1] - a[1]) * m_per_deg_lon
    py = (p[0] - a[0]) * m_per_deg_lat
    bx = (b[1] - a[1]) * m_per_deg_lon
    by = (b[0] - a[0]) * m_per_deg_lat

    seg_len_sq = bx * bx + by * by
    if seg_len_sq == 0:
        return math.hypot(px, py)
    t = max(0.0, min(1.0, (px * bx + py * by) / seg_len_sq))
    cx = t * bx
    cy = t * by
    return math.hypot(px - cx, py - cy)


# ---------------------------------------------------------------------------
# Graph loading + caching
# ---------------------------------------------------------------------------


def _cache_path(center_lat: float, center_lon: float, radius_m: int) -> Path:
    return CACHE_DIR / f"walk_{center_lat:.4f}_{center_lon:.4f}_r{radius_m}.graphml"


def load_graph(
    center_lat: float,
    center_lon: float,
    radius_m: int = DEFAULT_RADIUS_M,
    network_type: str = "walk",
    *,
    use_cache: bool = True,
) -> nx.MultiDiGraph:
    """Download (or load from disk cache) the OSM walking graph for an area.

    Calls ``osmnx.graph_from_point`` for the download and
    ``osmnx.save_graphml`` / ``osmnx.load_graphml`` for caching. We do
    not roll our own pickle — the GraphML round-trip preserves the
    edge attributes osmnx adds (length, geometry, highway, name, …).

    The 30 km default radius is intentional; smaller radii systematically
    fail to produce recognisable routes (see plan §0).
    """
    cache = _cache_path(center_lat, center_lon, radius_m)
    if use_cache and cache.exists():
        return ox.load_graphml(cache)
    G = ox.graph_from_point(
        (center_lat, center_lon),
        dist=radius_m,
        network_type=network_type,
        simplify=True,
    )
    if use_cache:
        ox.save_graphml(G, cache)
    return G


def nearest_node(G: nx.MultiDiGraph, lat: float, lon: float) -> int:
    """Snap a (lat, lon) to the closest graph node id. Thin wrapper over
    ``osmnx.distance.nearest_nodes`` so callers don't have to remember
    the (X=lon, Y=lat) calling convention."""
    return int(ox.distance.nearest_nodes(G, X=lon, Y=lat))


# ---------------------------------------------------------------------------
# Waschk & Krüger (2019) shape-aware edge cost
# ---------------------------------------------------------------------------


def waschk_kruger_cost_fn(
    G: nx.MultiDiGraph,
    seg_start: LatLon,
    seg_end: LatLon,
    alpha: float = 1.0,
    beta: float = 0.5,
    gamma: float = 4.0,
) -> Callable:
    """Return a ``weight(u, v, edge_data)`` callable suitable for
    ``networkx.shortest_path(..., weight=callable)``.

    The closure captures the current target outline segment so we can
    score every candidate edge against it. The weights default to a
    moderate emphasis on shape fidelity (γ > α > β) which empirically
    produces routes that hug the target without ignoring real road
    geometry. Tune via the ``shape_aware_route`` API.

    All three sub-costs are in metres so they're directly comparable
    without per-term normalisation.
    """
    def weight(u: int, v: int, edge_data: dict) -> float:
        # MultiDiGraph: edge_data may be the inner attribute dict (when
        # NetworkX picks a parallel edge), or a {key: attrs} mapping
        # (older callers). Handle both.
        if "length" not in edge_data and edge_data:
            # pick the shortest parallel edge
            inner = min(edge_data.values(), key=lambda d: d.get("length", float("inf")))
        else:
            inner = edge_data

        edge_length = float(inner.get("length", 0.0))

        v_lat = float(G.nodes[v]["y"])
        v_lon = float(G.nodes[v]["x"])
        u_lat = float(G.nodes[u]["y"])
        u_lon = float(G.nodes[u]["x"])

        # C1: haversine from new node to segment endpoint (metres)
        c1 = _haversine((v_lat, v_lon), seg_end)

        # C2: edge length (metres)
        c2 = edge_length

        # C3: perpendicular distance from edge midpoint to the target
        # segment a→b. Cheap proxy for the Riemann-sum of perpendicular
        # distances along the edge — for typical city-block edges (<200 m)
        # the midpoint is within a few percent of the integrated value.
        mid = ((u_lat + v_lat) / 2.0, (u_lon + v_lon) / 2.0)
        c3 = _point_to_segment_distance_m(mid, seg_start, seg_end)

        return alpha * c1 + beta * c2 + gamma * c3

    return weight


# ---------------------------------------------------------------------------
# Segment-by-segment shape-aware routing
# ---------------------------------------------------------------------------


@dataclass
class ShapeRouteResult:
    polyline: List[LatLon]      # full road-snapped (lat, lon) trace
    distance_m: float           # sum of edge lengths along the route
    n_segments_routed: int      # how many outline segments produced a path
    n_segments_failed: int      # how many fell back / were skipped


def _path_polyline_and_length(G: nx.MultiDiGraph, node_path: List[int]) -> Tuple[List[LatLon], float]:
    """Convert a node path to a (lat, lon) polyline and a total length."""
    coords: List[LatLon] = []
    length_m = 0.0
    for i, n in enumerate(node_path):
        coords.append((float(G.nodes[n]["y"]), float(G.nodes[n]["x"])))
        if i > 0:
            u, v = node_path[i - 1], n
            edge_data = G.get_edge_data(u, v)
            if edge_data:
                inner = min(edge_data.values(), key=lambda d: d.get("length", float("inf")))
                length_m += float(inner.get("length", 0.0))
    return coords, length_m


def shape_aware_route(
    G: nx.MultiDiGraph,
    outline_latlon: List[LatLon],
    *,
    alpha: float = 1.0,
    beta: float = 0.5,
    gamma: float = 4.0,
    closed: bool = True,
) -> ShapeRouteResult:
    """Route through the road graph following the outline shape.

    For each consecutive pair of outline points (S_i, S_{i+1}) we run
    Dijkstra from the previous segment's end-node to a node near
    S_{i+1}, with the Waschk-Krüger weight function. The router
    naturally prefers edges that run *alongside* the current segment.

    If two consecutive outline points snap to the same graph node we
    skip that segment. If Dijkstra finds no path we record a failure
    and snap to the next anchor node directly (the polyline gets a
    straight-line jump; downstream scoring will penalise it).

    Returns the concatenated polyline, total length, and per-segment
    success/failure counts.
    """
    if len(outline_latlon) < 2:
        raise ValueError("outline_latlon needs at least 2 points")

    pts = list(outline_latlon)
    if closed and pts[0] != pts[-1]:
        pts.append(pts[0])

    full_polyline: List[LatLon] = []
    total_length = 0.0
    n_ok = 0
    n_fail = 0

    # Snap every outline point once up front (cheap; saves repeated
    # KDTree queries when the same node serves consecutive segments).
    anchor_nodes = [nearest_node(G, lat, lon) for (lat, lon) in pts]

    for i in range(len(pts) - 1):
        u_node = anchor_nodes[i]
        v_node = anchor_nodes[i + 1]
        seg_start = pts[i]
        seg_end = pts[i + 1]

        if u_node == v_node:
            # Outline segment is shorter than the local node spacing;
            # nothing to route. Add the snapped point so the polyline
            # still includes the position.
            snapped = (float(G.nodes[u_node]["y"]), float(G.nodes[u_node]["x"]))
            if not full_polyline or full_polyline[-1] != snapped:
                full_polyline.append(snapped)
            continue

        weight = waschk_kruger_cost_fn(G, seg_start, seg_end, alpha, beta, gamma)
        try:
            node_path = nx.shortest_path(G, u_node, v_node, weight=weight)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            n_fail += 1
            # Straight snap to the next anchor; flag via the failure counter.
            snapped = (float(G.nodes[v_node]["y"]), float(G.nodes[v_node]["x"]))
            if not full_polyline or full_polyline[-1] != snapped:
                full_polyline.append(snapped)
            continue

        coords, length_m = _path_polyline_and_length(G, node_path)
        # Avoid duplicating the seam node between consecutive segments.
        if full_polyline and coords and full_polyline[-1] == coords[0]:
            full_polyline.extend(coords[1:])
        else:
            full_polyline.extend(coords)
        total_length += length_m
        n_ok += 1

    return ShapeRouteResult(
        polyline=full_polyline,
        distance_m=total_length,
        n_segments_routed=n_ok,
        n_segments_failed=n_fail,
    )
