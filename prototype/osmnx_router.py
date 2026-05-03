"""OSMnx-backed graph loader and segment-by-segment router.

This module:
- Loads a walking road network around a (lat, lon, radius) point and caches it
  to disk as GraphML so repeated searches are cheap.
- Projects normalized template coords (in [-0.5, 0.5]) onto lat/lon at a given
  (center, scale_m, rotation_deg).
- Routes between consecutive projected vertices using `nx.shortest_path` with
  edge length as the weight, returning the snapped polyline.

We deliberately do NOT use a custom shape-fidelity edge cost here. That trick
exists in Waschk-Krüger; the multi-template search compensates for lazy local
routing because *some* template variant will fit the local grid. Keeping
routing simple keeps each candidate fast (<200ms) so we can afford a wide
search over (template x placement x scale x rotation).
"""

from __future__ import annotations

import math
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import networkx as nx
import numpy as np
import osmnx as ox

warnings.filterwarnings('ignore', category=UserWarning, module='osmnx')

# Earth radius (m) — good enough for sub-50km local projections.
_R = 6_371_000.0


def project_template(
    coords: List[Tuple[float, float]],
    center_lat: float,
    center_lon: float,
    scale_m: float,
    rotation_deg: float = 0.0,
) -> List[Tuple[float, float]]:
    """Project unit-box template coords onto (lat, lon).

    `scale_m` is the bounding-box size of the projected shape in meters.
    Returns list of (lat, lon).
    """
    theta = math.radians(rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    # meters-per-degree at this latitude
    m_per_deg_lat = _R * math.pi / 180.0
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(center_lat))

    out = []
    for x, y in coords:
        # rotate
        rx = x * cos_t - y * sin_t
        ry = x * sin_t + y * cos_t
        # scale to meters then convert to lat/lon offsets
        dx_m = rx * scale_m
        dy_m = ry * scale_m
        lat = center_lat + dy_m / m_per_deg_lat
        lon = center_lon + dx_m / m_per_deg_lon
        out.append((lat, lon))
    return out


@dataclass
class GraphHandle:
    G: nx.MultiDiGraph
    center_lat: float
    center_lon: float
    radius_m: int


def load_graph(
    center_lat: float,
    center_lon: float,
    radius_m: int = 8_000,
    cache_dir: str = 'data/graph_cache',
) -> GraphHandle:
    """Load a walking road graph; disk-cached as GraphML."""
    os.makedirs(cache_dir, exist_ok=True)
    key = f'{center_lat:.4f}_{center_lon:.4f}_{radius_m}'
    cache_path = Path(cache_dir) / f'{key}.graphml'
    if cache_path.exists():
        G = ox.load_graphml(cache_path)
    else:
        G = ox.graph_from_point(
            (center_lat, center_lon),
            dist=radius_m,
            network_type='walk',
            simplify=True,
        )
        ox.save_graphml(G, cache_path)
    return GraphHandle(G=G, center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)


def _haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _R * math.asin(math.sqrt(a))


def route_through_template(
    handle: GraphHandle,
    projected: List[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    """Route through projected vertices via shortest paths between consecutive nodes.

    Returns a list of (lat, lon) snapped to the road graph. If a hop fails,
    the straight target vertex is appended to keep the polyline continuous.
    """
    G = handle.G
    # Snap each vertex to nearest graph node — vectorized for speed
    lats = [p[0] for p in projected]
    lons = [p[1] for p in projected]
    nodes = ox.distance.nearest_nodes(G, X=lons, Y=lats)

    full: List[Tuple[float, float]] = []
    for i in range(len(nodes) - 1):
        u, v = nodes[i], nodes[i + 1]
        if u == v:
            continue
        try:
            path = nx.shortest_path(G, u, v, weight='length')
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            full.append(projected[i + 1])
            continue
        coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in path]
        if full:
            coords = coords[1:]  # avoid dup
        full.extend(coords)
    return full


def route_length_m(route: List[Tuple[float, float]]) -> float:
    return sum(
        _haversine(a[0], a[1], b[0], b[1])
        for a, b in zip(route, route[1:])
    )


__all__ = [
    'GraphHandle',
    'load_graph',
    'project_template',
    'route_through_template',
    'route_length_m',
]
