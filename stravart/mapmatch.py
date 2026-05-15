"""Snap a georeferenced polyline to the OSM street network.

Phase 3 input: a noisy polyline in (lat, lon) — the contour extracted from
the strav.art image and projected through the affine pixel→geo transform.
Phase 3 output: a clean polyline that follows actual streets, ready to be
written as a GPX route.

We use OSMnx for the OSM graph + nearest-node lookups. Map matching is done
by:

    1. Downsampling the contour to a small set of waypoints (every ~30 m,
       configurable). The contour is dense (1 vertex per skeleton pixel),
       so feeding every vertex into shortest_path is wasteful.
    2. ``ox.distance.nearest_nodes`` on each waypoint to snap it to the
       closest graph node.
    3. ``nx.shortest_path`` between each consecutive snapped pair using
       ``edge['length']`` as the weight. We concatenate the per-segment
       node sequences (deduping the boundary node).
    4. Reading back each node's (y, x) attrs to build the matched polyline.

Why not Valhalla/Meili? They're the gold standard for noisy GPS, but they
require a server (or `valhalla_run_isochrone`-style native bindings that
are platform-specific). OSMnx + Dijkstra-per-segment is good enough for our
"trace looks roughly like the route" use case and runs in pure Python.

The graph itself is fetched once via ``ox.graph.graph_from_bbox`` against
the contour bounding box (with padding from ``georef.bbox_of_geocoords``).
For batch use, the caller can pre-compute / cache graphs by bbox.

This module is pure-Python except for OSMnx's internal HTTPS call to
Overpass during graph download. Tests mock the graph object; no network.
"""

from __future__ import annotations

import itertools
import logging
import math
import os
from dataclasses import dataclass

import networkx as nx
import numpy as np

from .fidelity_score import discrete_frechet_m


logger = logging.getLogger(__name__)


def _ensure_macos_keychain_ca_for_requests() -> None:
    """Make ``requests``/``urllib3`` (used by OSMnx for Overpass) trust the
    macOS keychain.

    OSMnx's Overpass calls go through ``requests`` rather than ``httpx``, so
    the SSL context configured in :mod:`stravart.crossref` doesn't apply.
    On corporate-proxied macOS hosts the system root store includes a
    self-signed cert that ``certifi``'s bundle does not, and the call
    fails with ``SSL_VERIFY_FAILED``. Setting ``REQUESTS_CA_BUNDLE`` (and
    ``SSL_CERT_FILE``) to the keychain dump from
    :func:`stravart.crossref._macos_keychain_bundle` lets the existing
    cached bundle do the same job for ``requests``.

    No-op on non-macOS or when the bundle has already been exported.
    """
    if "REQUESTS_CA_BUNDLE" in os.environ and os.path.exists(os.environ["REQUESTS_CA_BUNDLE"]):
        return
    try:
        from .crossref import _macos_keychain_bundle
    except Exception:                                              # noqa: BLE001
        return
    bundle = _macos_keychain_bundle()
    if bundle:
        os.environ["REQUESTS_CA_BUNDLE"] = bundle
        os.environ.setdefault("SSL_CERT_FILE", bundle)


_ensure_macos_keychain_ca_for_requests()


# ---------------------------------------------------- waypoint sampling

_EARTH_R_M = 6371000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_R_M * math.asin(min(1.0, math.sqrt(a)))


def downsample_by_distance(
    coords: list[tuple[float, float]],
    *,
    step_m: float = 30.0,
    return_indices: bool = False,
):
    """Reduce a dense lat/lon polyline to waypoints ~``step_m`` apart.

    Always keeps the first and last vertex. Walks the polyline forward,
    accumulating arc-length, and emits a waypoint every ``step_m`` metres.
    Used to feed shortest-path segment endpoints — feeding every contour
    pixel through Dijkstra is wasteful and the per-pixel jitter dominates
    the snap step anyway.

    When ``return_indices=True``, returns ``(waypoints, indices)`` where
    ``indices[i]`` is the index into the original ``coords`` for
    ``waypoints[i]``. Phase 4b's shape-aware map-match uses this to slice
    the projected contour into the reference sub-segment between
    consecutive waypoint pairs.
    """
    if not coords:
        return ([], []) if return_indices else []
    if len(coords) == 1:
        return ([coords[0]], [0]) if return_indices else [coords[0]]

    out = [coords[0]]
    idxs = [0]
    accum = 0.0
    for i in range(1, len(coords)):
        prev, curr = coords[i - 1], coords[i]
        accum += _haversine_m(prev[0], prev[1], curr[0], curr[1])
        if accum >= step_m:
            out.append(curr)
            idxs.append(i)
            accum = 0.0
    if out[-1] != coords[-1]:
        out.append(coords[-1])
        idxs.append(len(coords) - 1)
    return (out, idxs) if return_indices else out


# ---------------------------------------------------- graph download

def load_graph(
    bbox: tuple[float, float, float, float],
    *,
    network_type: str = "walk",
    simplify: bool = True,
):
    """Fetch the OSM walkable network for ``bbox`` (S, N, W, E) via OSMnx.

    Imported lazily so the package can be loaded in environments without
    network access; only callers that actually map-match pay the import +
    Overpass round-trip.
    """
    import osmnx as ox

    south, north, west, east = bbox
    return ox.graph.graph_from_bbox(
        bbox=(west, south, east, north),
        network_type=network_type,
        simplify=simplify,
    )


# ---------------------------------------------------- snapping

@dataclass(frozen=True)
class MatchedRoute:
    """Result of map-matching one polyline."""

    coords: list[tuple[float, float]]   # (lat, lon) along snapped streets
    node_ids: list[int]                 # OSM node ids on the chosen path
    length_m: float                     # arc length of the snapped polyline
    waypoints_used: int                 # downsampled waypoints fed to Dijkstra
    snapped_pairs: int                  # consecutive (u, v) pairs Dijkstra ran on
    unreachable_segments: int           # segments where networkx couldn't connect
    reranked_segments: int = 0          # segments where shape-rerank chose a non-shortest path


def _node_xy(graph, node_id) -> tuple[float, float]:
    """Read (lat, lon) from the OSM graph node attrs."""
    data = graph.nodes[node_id]
    # OSMnx stores y=lat, x=lon — see https://osmnx.readthedocs.io/en/stable/.
    return float(data["y"]), float(data["x"])


def _path_length_m(graph, node_seq: list[int]) -> float:
    """Sum of ``edge['length']`` along ``node_seq``. Handles MultiDiGraph parallel
    edges by picking the shortest edge between each pair (mirrors what
    Dijkstra would have used)."""
    total = 0.0
    for u, v in zip(node_seq, node_seq[1:]):
        edges = graph.get_edge_data(u, v)
        if not edges:
            continue
        # MultiDiGraph: edges = {key: attrs, ...}. DiGraph: edges = attrs.
        if isinstance(edges, dict) and any(isinstance(val, dict) for val in edges.values()):
            length = min(
                float(attrs.get("length", 0.0))
                for attrs in edges.values()
                if isinstance(attrs, dict)
            )
        else:
            length = float(edges.get("length", 0.0))
        total += length
    return total


def _candidate_paths(graph, u: int, v: int, *, k: int) -> list[list[int]]:
    """Top-K simple shortest paths from ``u`` to ``v``, weighted by ``length``.

    Falls back to a single Dijkstra path if the simple-paths generator
    raises (some MultiDiGraph corners). Returns at most ``k`` paths,
    fewer if the graph doesn't offer that many alternatives.
    """
    try:
        gen = nx.shortest_simple_paths(graph, u, v, weight="length")
        return list(itertools.islice(gen, k))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []
    except Exception:                                                # noqa: BLE001
        # `shortest_simple_paths` requires the graph be simple in some
        # NetworkX versions; fall back to single Dijkstra.
        try:
            return [nx.shortest_path(graph, u, v, weight="length")]
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []


def _path_shape_deviation_m(
    graph,
    node_seq: list[int],
    reference: list[tuple[float, float]],
) -> float:
    """Discrete Fréchet distance between a node sequence and a reference polyline.

    Both are converted to (lat, lon) lists; the existing shared-origin
    Fréchet helper in :mod:`stravart.fidelity_score` handles the projection
    to a local metric frame. Returns ``inf`` if either side is empty.
    """
    if not node_seq or not reference:
        return float("inf")
    path_latlon = [_node_xy(graph, n) for n in node_seq]
    return discrete_frechet_m(path_latlon, reference)


def map_match(
    coords: list[tuple[float, float]],
    graph,
    *,
    waypoint_step_m: float = 30.0,
    k_shortest_paths: int = 1,
    rerank: str = "shape",
) -> MatchedRoute:
    """Snap ``coords`` to streets in ``graph`` and return the routed polyline.

    Algorithm (Phase 4b shape-aware path selection — opt-in):
        * Downsample to waypoints every ``waypoint_step_m`` metres
          (default 30 m, same as Phase 3 — the rerank-machinery is opt-in
          via ``k_shortest_paths > 1`` because empirically dense waypoints
          collapse the K=3 candidate set to 1 path per segment, leaving
          nothing to rerank).
        * Snap each waypoint to its nearest OSM node (ox.nearest_nodes).
        * For each consecutive snapped pair, generate the top
          ``k_shortest_paths`` candidate paths weighted by edge length.
        * When ``rerank="shape"`` and K > 1, **rerank candidates by
          discrete Fréchet distance to the reference contour segment**
          (the slice of the input ``coords`` between this waypoint pair).
          The winner is the path whose street geometry best matches the
          cartoon's shape — not the shortest one. This addresses the
          "elephant trunk takes wrong turn" failure mode from PoC run #2.
        * Concatenate per-segment node sequences, deduping boundary nodes.

    Backwards compatibility:
        * ``k_shortest_paths=1`` reduces to the original Dijkstra-only
          behaviour.
        * ``rerank="length"`` ignores the contour shape and picks
          shortest-by-length even when K>1 (useful for ablation).

    Returns the snapped coordinate list, OSM node ids, total length, and
    diagnostics. Raises nothing on graph-misses; everything is reported.
    """
    if len(coords) < 2:
        return MatchedRoute(
            coords=list(coords), node_ids=[], length_m=0.0,
            waypoints_used=len(coords), snapped_pairs=0,
            unreachable_segments=0,
        )

    import osmnx as ox

    waypoints, wp_indices = downsample_by_distance(
        coords, step_m=waypoint_step_m, return_indices=True,
    )
    if len(waypoints) < 2:
        return MatchedRoute(
            coords=list(waypoints), node_ids=[], length_m=0.0,
            waypoints_used=len(waypoints), snapped_pairs=0,
            unreachable_segments=0,
        )

    lats = [c[0] for c in waypoints]
    lons = [c[1] for c in waypoints]
    snapped = ox.distance.nearest_nodes(graph, X=lons, Y=lats)

    node_path: list[int] = []
    unreachable = 0
    pairs_run = 0
    reranked = 0
    for i, (u, v) in enumerate(zip(snapped, snapped[1:])):
        if u == v:
            # Two waypoints both snapped to the same node — nothing to do.
            continue
        pairs_run += 1
        candidates = _candidate_paths(graph, u, v, k=max(1, k_shortest_paths))
        if not candidates:
            unreachable += 1
            continue

        if len(candidates) == 1 or rerank != "shape":
            best = candidates[0]
        else:
            # Reference shape: the projected-contour sub-segment that this
            # waypoint pair brackets. We use the ORIGINAL dense polyline,
            # not the downsampled waypoints, because the shape detail lives
            # in the bends between waypoints.
            ref_start = wp_indices[i]
            ref_end = wp_indices[i + 1]
            reference = coords[ref_start : ref_end + 1]
            if len(reference) < 2:
                best = candidates[0]
            else:
                scored = [
                    (_path_shape_deviation_m(graph, p, reference), p)
                    for p in candidates
                ]
                scored.sort(key=lambda sp: sp[0])
                best = scored[0][1]
                if best is not candidates[0]:
                    reranked += 1

        if not node_path:
            node_path.extend(best)
        else:
            # Skip the first node of seg if it equals the path's tail
            # (otherwise we'd double-count the boundary node).
            if best and best[0] == node_path[-1]:
                node_path.extend(best[1:])
            else:
                node_path.extend(best)

    snapped_coords = [_node_xy(graph, n) for n in node_path]
    length = _path_length_m(graph, node_path)
    return MatchedRoute(
        coords=snapped_coords,
        node_ids=node_path,
        length_m=length,
        waypoints_used=len(waypoints),
        snapped_pairs=pairs_run,
        unreachable_segments=unreachable,
        reranked_segments=reranked,
    )
