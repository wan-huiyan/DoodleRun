"""Fast pre-screen of candidate areas before full shape-aware routing.

Three cheap features kill the vast majority of unworkable candidates
without paying the Dijkstra cost:

  1. **Road density** — total edge length per km². Areas below a
     threshold (5 km/km² by default) are too sparse for any animal
     route to read.
  2. **Grid regularity** — variance of edge bearings. A neat grid
     scores low (most edges align to two perpendicular directions).
     Wildly irregular networks score high. We don't *reject* on this —
     irregular networks can still produce great routes — but it's a
     diagnostic the search uses for tie-breaks.
  3. **Connectivity** — the largest weakly-connected component must
     cover ≥70% of nodes. Disconnected fragments (parks, rivers,
     railways carved into the network) systematically kill long routes.

Implementation: lean on OSMnx primitives. ``ox.basic_stats`` gives us
density-of-everything in one call; ``ox.bearing.add_edge_bearings``
adds the bearings we need for the regularity score; the connected
component check is plain NetworkX.

Public API:

    prescreen(G, *, min_density=5.0, min_connected_fraction=0.7) -> bool
    road_density_km(G) -> float                 # km/km²
    grid_regularity(G) -> float                 # 0 = perfect grid, 1 = chaos
    is_connected(G, min_fraction=0.7) -> bool

All three feature functions are independently useful for tuning and
diagnostics, so callers can read them piecemeal.
"""

from __future__ import annotations

import math
from typing import Tuple

import networkx as nx
import numpy as np
import osmnx as ox

# Default thresholds — calibrated from the W&K paper plus quick checks
# against London E14 (very dense, ~25 km/km²), SF Sunset (~16),
# rural Cotswolds (~2). Tune in tests, not by editing here.
DEFAULT_MIN_DENSITY_KM = 5.0
DEFAULT_MIN_CONNECTED_FRACTION = 0.7


def road_density_km(G: nx.MultiDiGraph) -> float:
    """Edge length per km².

    We compute this directly rather than via ``ox.basic_stats``: the
    latter requires an undirected projection and a usable bbox area,
    and falls over on synthetic test graphs that don't have a
    ``country`` tag. Direct sum of ``length`` ÷ bbox area gives the
    same answer for the comparison we care about.

    Returns 0 if the area can't be computed (degenerate bbox).
    """
    if not G.edges:
        return 0.0
    # MultiDiGraph stores both directions of each undirected segment,
    # so divide by 2 to get the road network's "physical" length.
    edge_total_m = sum(float(d.get("length", 0.0))
                       for _, _, _, d in G.edges(keys=True, data=True))
    if not isinstance(G, nx.MultiGraph) or G.is_directed():
        edge_total_m /= 2.0
    if edge_total_m <= 0:
        return 0.0
    area_km2 = _approx_area_km2(G)
    if area_km2 <= 0:
        return 0.0
    return (edge_total_m / 1000.0) / area_km2


def _approx_area_km2(G: nx.MultiDiGraph) -> float:
    """Bounding-box area in km² (cheap proxy for the convex hull area)."""
    if not G.nodes:
        return 0.0
    lats = [float(d["y"]) for _, d in G.nodes(data=True)]
    lons = [float(d["x"]) for _, d in G.nodes(data=True)]
    lat_span_km = (max(lats) - min(lats)) * 111.32
    mid_lat = (min(lats) + max(lats)) / 2
    lon_span_km = (max(lons) - min(lons)) * 111.32 * math.cos(math.radians(mid_lat))
    return max(lat_span_km * lon_span_km, 0.0)


def grid_regularity(G: nx.MultiDiGraph, *, num_bins: int = 36) -> float:
    """Score how grid-like the network is. 0 = perfect grid (bearings
    cluster in just a few bins), 1 = bearings uniformly scattered (max
    entropy).

    Uses ``ox.bearing.orientation_entropy`` — the canonical OSMnx
    metric — and rescales it onto [0, 1] by dividing by the maximum
    entropy of a uniform distribution over ``num_bins`` (log(num_bins)).
    Bearings are computed lazily; if ``G`` doesn't already carry them,
    we add them in place via ``ox.bearing.add_edge_bearings``.

    A simple folded-bearing variance breaks down because 89.999° and
    0° are perceptually near-identical (one is just below the fold)
    but appear maximally far in linear units — using the canonical
    circular statistic avoids that trap.
    """
    if not G.edges:
        return 1.0
    try:
        first_edge = next(iter(G.edges(data=True)))
    except StopIteration:
        return 1.0
    H = ox.bearing.add_edge_bearings(G) if "bearing" not in first_edge[2] else G
    try:
        entropy = ox.bearing.orientation_entropy(H, num_bins=num_bins)
    except Exception:
        return 1.0
    max_entropy = math.log(num_bins) if num_bins > 1 else 1.0
    return float(min(1.0, max(0.0, entropy / max_entropy)))


def is_connected(G: nx.MultiDiGraph, min_fraction: float = DEFAULT_MIN_CONNECTED_FRACTION) -> bool:
    """True iff the largest weakly-connected component covers at least
    ``min_fraction`` of all nodes. Cheap O(V + E)."""
    if not G.nodes:
        return False
    components = list(nx.weakly_connected_components(G))
    if not components:
        return False
    largest = max(len(c) for c in components)
    return (largest / len(G.nodes)) >= min_fraction


def prescreen(
    G: nx.MultiDiGraph,
    *,
    min_density_km: float = DEFAULT_MIN_DENSITY_KM,
    min_connected_fraction: float = DEFAULT_MIN_CONNECTED_FRACTION,
) -> Tuple[bool, dict]:
    """Combined pass/fail decision plus the diagnostic features used.

    Returns ``(ok, info)`` where ``info`` is a dict of the three
    sub-scores plus the final reason if rejected. Callers can drop the
    ``info`` and use just the bool — the diagnostics are there so the
    Optuna search can log why a candidate was pruned.
    """
    info = {
        "road_density_km": road_density_km(G),
        "grid_regularity": grid_regularity(G),
        "is_connected": is_connected(G, min_connected_fraction),
        "rejected_for": None,
    }
    if not info["is_connected"]:
        info["rejected_for"] = "connectivity"
        return False, info
    if info["road_density_km"] < min_density_km:
        info["rejected_for"] = "density"
        return False, info
    return True, info
