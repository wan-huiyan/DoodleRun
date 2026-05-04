"""Shared pytest fixtures and import-path setup.

Adds the prototype directory to sys.path so tests can `import pig_shape`,
`from osrm_client import …`, etc., without an installable package.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import networkx as nx
import pytest

PROTOTYPE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROTOTYPE_DIR))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def osrm_route_response() -> dict:
    """Recorded /route/v1/foot response with 4 waypoints in SF Sunset."""
    with open(FIXTURE_DIR / "osrm_route.json") as f:
        return json.load(f)


def make_grid_graph(n: int = 5, spacing_m: float = 100.0,
                    origin_lat: float = 37.0, origin_lon: float = -122.0) -> nx.MultiDiGraph:
    """Build a synthetic n×n MultiDiGraph standing in for an OSMnx walking
    graph. Each node has y/x (lat/lon) attributes; each edge has a length
    attribute and a tiny key=0 wrapper, matching what `ox.graph_from_point`
    produces after `simplify=True`. Reused across router/prescreener tests.
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
def grid_graph_factory():
    """Yield the factory itself so tests can build grids of varying size."""
    return make_grid_graph
