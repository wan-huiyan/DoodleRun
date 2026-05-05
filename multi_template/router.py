"""Shape-aware Dijkstra router (Waschk-Krüger C₃ cost) with anti-revisit.

Given a target outline (template projected to lat/lon waypoints), we route
through the waypoints in order. For each leg we run Dijkstra on the OSMnx
MultiDiGraph with a per-edge cost:

    c(e) = length_m * (1 + alpha * angle_dev) + beta * perp_dist_m
           + revisit_penalty_m * already_used(e)

- angle_dev = |bearing(e) - bearing(leg)| folded to [0, π/2], normalized
- perp_dist_m = distance from edge midpoint to the leg line segment
- revisit penalty (default 4000 m) is the lesson from prior iterations:
  prevents the route from re-using edges to make a "spaghetti" path.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx

from .graph_loader import EARTH_R_M, _haversine_m


@dataclass
class RouteLeg:
    nodes: List[int]
    polyline: List[Tuple[float, float]]  # (lat, lon)
    length_m: float


@dataclass
class RoutedShape:
    waypoints: List[Tuple[float, float]]   # the (lat, lon) shape vertices we asked the router to hit
    legs: List[RouteLeg]
    polyline: List[Tuple[float, float]]
    total_length_m: float
    used_edges: Set[Tuple[int, int]] = field(default_factory=set)


def _project_perp_m(lat: float, lon: float,
                    a_lat: float, a_lon: float,
                    b_lat: float, b_lon: float) -> float:
    """Approximate perpendicular distance from (lat, lon) to segment a→b in metres.

    Uses local equirectangular projection — fine for legs < 5 km."""
    ref_lat = (a_lat + b_lat) * 0.5
    cos_lat = math.cos(math.radians(ref_lat))
    mlon = lambda lo: math.radians(lo) * EARTH_R_M * cos_lat
    mlat = lambda la: math.radians(la) * EARTH_R_M
    px, py = mlon(lon), mlat(lat)
    ax, ay = mlon(a_lon), mlat(a_lat)
    bx, by = mlon(b_lon), mlat(b_lat)
    abx, aby = bx - ax, by - ay
    L2 = abx * abx + aby * aby
    if L2 <= 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / L2))
    qx, qy = ax + t * abx, ay + t * aby
    return math.hypot(px - qx, py - qy)


def _bearing_dev(leg_bearing: float, edge_bearing: float) -> float:
    """Folded angle deviation in [0, π/2]; lower = aligned (or anti-aligned)."""
    d = abs((edge_bearing - leg_bearing + math.pi) % (2 * math.pi) - math.pi)
    if d > math.pi / 2:
        d = math.pi - d
    return d


def _make_cost_fn(
    leg_a: Tuple[float, float],
    leg_b: Tuple[float, float],
    used_edges: Set[Tuple[int, int]],
    *,
    alpha: float,
    beta: float,
    revisit_penalty_m: float,
):
    leg_bearing = math.atan2(
        math.sin(math.radians(leg_b[1] - leg_a[1])) * math.cos(math.radians(leg_b[0])),
        math.cos(math.radians(leg_a[0])) * math.sin(math.radians(leg_b[0]))
        - math.sin(math.radians(leg_a[0])) * math.cos(math.radians(leg_b[0])) * math.cos(math.radians(leg_b[1] - leg_a[1])),
    )

    def cost(u, v, data_or_keymap):
        # Handle both MultiDiGraph (outer key→attrs map) and DiGraph (inner attrs).
        if data_or_keymap and isinstance(next(iter(data_or_keymap.values()), None), dict) and "_length_m" not in data_or_keymap:
            attrs_iter = data_or_keymap.values()
        else:
            attrs_iter = [data_or_keymap]
        best = math.inf
        for d in attrs_iter:
            length_m = d["_length_m"]
            ang = _bearing_dev(leg_bearing, d["_bear_rad"])
            perp = _project_perp_m(d["_mid_lat"], d["_mid_lon"], leg_a[0], leg_a[1], leg_b[0], leg_b[1])
            c = length_m * (1.0 + alpha * (ang / (math.pi / 2))) + beta * perp
            if (u, v) in used_edges or (v, u) in used_edges:
                c += revisit_penalty_m
            if c < best:
                best = c
        return best

    return cost


def _polyline_for_leg(G: nx.MultiDiGraph, nodes: List[int]) -> Tuple[List[Tuple[float, float]], float]:
    pts = []
    total = 0.0
    for i, n in enumerate(nodes):
        d = G.nodes[n]
        pts.append((d["y"], d["x"]))
        if i > 0:
            data = G.get_edge_data(nodes[i - 1], n)
            if data:
                vals = list(data.values()) if isinstance(next(iter(data.values()), None), dict) else [data]
                total += min(v["_length_m"] for v in vals)
    return pts, total


def route_through_waypoints(
    G: nx.MultiDiGraph,
    waypoints: List[Tuple[float, float]],
    *,
    alpha: float = 3.0,
    beta: float = 2.5,
    revisit_penalty_m: float = 4000.0,
) -> Optional[RoutedShape]:
    """Snap each waypoint to the nearest graph node, then shape-aware-Dijkstra
    each leg, accumulating an anti-revisit penalty as we go."""
    import osmnx as ox

    lats = [w[0] for w in waypoints]
    lons = [w[1] for w in waypoints]
    snapped = ox.distance.nearest_nodes(G, lons, lats)
    snapped = list(dict.fromkeys(snapped))   # dedupe keeping order
    if len(snapped) < 2:
        return None

    used: Set[Tuple[int, int]] = set()
    legs: List[RouteLeg] = []
    full_poly: List[Tuple[float, float]] = []
    total = 0.0
    for i in range(len(snapped) - 1):
        a_node, b_node = snapped[i], snapped[i + 1]
        a_pt = (G.nodes[a_node]["y"], G.nodes[a_node]["x"])
        b_pt = (G.nodes[b_node]["y"], G.nodes[b_node]["x"])
        cost = _make_cost_fn(a_pt, b_pt, used,
                             alpha=alpha, beta=beta, revisit_penalty_m=revisit_penalty_m)
        try:
            path = nx.shortest_path(G, a_node, b_node, weight=cost)
        except nx.NetworkXNoPath:
            return None
        poly, leg_len = _polyline_for_leg(G, path)
        if not full_poly:
            full_poly.extend(poly)
        else:
            full_poly.extend(poly[1:])
        total += leg_len
        for j in range(len(path) - 1):
            used.add((path[j], path[j + 1]))
        legs.append(RouteLeg(nodes=path, polyline=poly, length_m=leg_len))

    return RoutedShape(
        waypoints=[(G.nodes[n]["y"], G.nodes[n]["x"]) for n in snapped],
        legs=legs,
        polyline=full_poly,
        total_length_m=total,
        used_edges=used,
    )
