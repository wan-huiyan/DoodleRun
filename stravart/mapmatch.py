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
    via_nodes_pinned: int = 0           # Phase 4b option 4: OCR-anchor nodes forced into the path
    mode: str = "dijkstra"              # Phase 4c: which matcher produced this — "dijkstra" or "hmm"
    hmm_states_emitted: int = 0         # Phase 4c (hmm mode): # distinct edges in Viterbi trace
    hmm_unreachable_stitches: int = 0   # Phase 4c (hmm mode): # gaps where Dijkstra couldn't connect adjacent matched nodes


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
    via_nodes: list[tuple[float, float, int]] | None = None,
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

    Phase 4b option 4 — ``via_nodes``:
        ``via_nodes`` is a list of ``(lat, lon, osm_node_id)`` tuples
        representing hard via-points: streets the OCR has identified
        with high confidence (the inlier GCPs that survived RANSAC).
        Each via-node is inserted into the waypoint sequence at the
        contour position closest to its (lat, lon), and its snapped
        OSM node is **forced** to be the supplied ``osm_node_id``
        (overriding what ``ox.nearest_nodes`` would have chosen).
        Dijkstra is then routed THROUGH these pinned nodes in order
        — the OCR-identified intersections become a hard skeleton
        the cartoon must follow. This addresses the wrong-turn snap
        problem (#584 elephant's trunk pointing the wrong way) by
        using the pipeline's strongest signal (OCR street IDs) as
        routing constraints, not just affine-projection anchors.

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

    # Option 4: inject via_nodes at their natural positions along the contour.
    # For each via (lat, lon, node_id), find the coords-index nearest to it,
    # then insert into ``waypoints`` so that consecutive Dijkstra runs route
    # THROUGH the via-node. ``via_overrides`` maps the waypoint index of each
    # injected via-node to its forced node_id (skips nearest_nodes for that
    # waypoint). Injection preserves the existing waypoint order — we never
    # reorder the cartoon's natural sequence.
    via_overrides: dict[int, int] = {}    # waypoint_index → node_id
    if via_nodes:
        # Build (coords-index, via_entry) for each via, sorted by coords order.
        via_positions: list[tuple[int, tuple[float, float, int]]] = []
        for via_lat, via_lon, via_node_id in via_nodes:
            # Nearest contour point in coords (linear scan; coords are typically
            # few thousand points → microseconds)
            best_idx = 0
            best_d = float("inf")
            for i, (clat, clon) in enumerate(coords):
                d = _haversine_m(clat, clon, via_lat, via_lon)
                if d < best_d:
                    best_d = d
                    best_idx = i
            via_positions.append((best_idx, (via_lat, via_lon, via_node_id)))
        via_positions.sort(key=lambda p: p[0])

        # Merge into waypoints sequence. For each via, find the insertion
        # point in wp_indices such that the via's contour-index sits between
        # consecutive waypoint indices. Insert + record override.
        new_waypoints: list[tuple[float, float]] = []
        new_wp_indices: list[int] = []
        via_cursor = 0
        for i, wp_idx in enumerate(wp_indices):
            # Drain any vias whose contour-index is ≤ this waypoint's
            while via_cursor < len(via_positions) and via_positions[via_cursor][0] <= wp_idx:
                v_idx, (vlat, vlon, vnode) = via_positions[via_cursor]
                # Don't double-insert if a previously-inserted via had the same idx
                if not new_wp_indices or new_wp_indices[-1] < v_idx:
                    new_waypoints.append((vlat, vlon))
                    new_wp_indices.append(v_idx)
                    via_overrides[len(new_waypoints) - 1] = vnode
                via_cursor += 1
            new_waypoints.append(waypoints[i])
            new_wp_indices.append(wp_idx)
        # Drain any remaining vias past the last waypoint
        while via_cursor < len(via_positions):
            v_idx, (vlat, vlon, vnode) = via_positions[via_cursor]
            new_waypoints.append((vlat, vlon))
            new_wp_indices.append(v_idx)
            via_overrides[len(new_waypoints) - 1] = vnode
            via_cursor += 1

        waypoints = new_waypoints
        wp_indices = new_wp_indices

    lats = [c[0] for c in waypoints]
    lons = [c[1] for c in waypoints]
    snapped = list(ox.distance.nearest_nodes(graph, X=lons, Y=lats))
    # Force via positions to their OCR-identified node ids.
    for idx, node_id in via_overrides.items():
        if 0 <= idx < len(snapped):
            snapped[idx] = node_id

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
        via_nodes_pinned=len(via_overrides),
        mode="dijkstra",
    )


# ---------------------------------------------------- Phase 4c: HMM matcher
#
# Streams A-of-3 in Phase 4c: a Hidden Markov Model (Newson-Krumm style) map
# matcher. The Dijkstra-per-segment matcher above operates LOCALLY — it makes
# one snap decision per waypoint pair, and a single mis-snap (the cartoon
# trunk pointing the wrong way) propagates downstream. The HMM scores
# *entire path likelihoods* against the observed shape, so an early
# ambiguous observation is re-resolved by later observations that are
# unambiguous.
#
# Implementation: ``leuvenmapmatching`` (pure-Python; standard Newson-Krumm
# matcher on PyPI; takes a graph + observations, runs Viterbi over edge
# states, returns the most-likely edge sequence). We adapt our OSMnx
# MultiDiGraph into the library's ``InMemMap`` and post-process the matched
# edges back into the same ``MatchedRoute`` shape as the Dijkstra path.
#
# Why a library rather than rolling Viterbi by hand: per the predecessor
# handoff and project axiom "use libraries over re-implementation" —
# leuvenmapmatching is well-tested, handles non-emitting states, and gives
# us a documented algorithm we can compare against rather than introducing
# our own Viterbi bugs.


def _build_inmem_map(graph):
    """Convert an OSMnx-style ``MultiDiGraph`` into a ``leuvenmapmatching``
    ``InMemMap`` for HMM matching.

    Each OSMnx node becomes an InMemMap node carrying (lat, lon). Each
    directed edge becomes an InMemMap directed edge. Parallel edges (the
    MultiDiGraph case) collapse to one InMemMap edge — the HMM doesn't
    care about parallel-edge geometry because the observations bracket
    *which* edge was used by their proximity to it.
    """
    from leuvenmapmatching.map.inmem import InMemMap

    imap = InMemMap("osmnx", use_latlon=True)
    for node_id, data in graph.nodes(data=True):
        lat = float(data["y"])
        lon = float(data["x"])
        imap.add_node(node_id, (lat, lon))
    seen_edges: set[tuple[int, int]] = set()
    for u, v in graph.edges():
        if (u, v) in seen_edges:
            continue
        imap.add_edge(u, v)
        seen_edges.add((u, v))
    return imap


def _stitch_node_path(
    graph,
    matched_node_seq: list[int],
) -> tuple[list[int], int]:
    """Turn the HMM's matched-node sequence into a contiguous graph walk.

    The HMM returns a list of nodes implied by its matched edge sequence
    (``[u_0, v_0, v_1, ...]``). Two consecutive entries may not be directly
    connected in the OSMnx graph if the HMM emitted a non-emitting node
    between them (e.g. when the matcher steps across a long edge). We call
    ``nx.shortest_path`` to stitch each non-adjacent pair into a walk. The
    returned sequence has consecutive duplicates removed.

    Returns ``(node_path, unreachable_count)`` — ``unreachable_count``
    increments whenever ``shortest_path`` raised ``NetworkXNoPath`` (rare;
    indicates the HMM produced a node pair that's actually disconnected
    in the graph subset).
    """
    if not matched_node_seq:
        return [], 0
    out: list[int] = [matched_node_seq[0]]
    unreachable = 0
    for u, v in zip(matched_node_seq, matched_node_seq[1:]):
        if u == v:
            continue
        # Direct edge in either direction is cheapest — skip Dijkstra.
        if graph.has_edge(u, v) or graph.has_edge(v, u):
            if out[-1] != u:
                out.append(u)
            out.append(v)
            continue
        try:
            sub = nx.shortest_path(graph, u, v, weight="length")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            unreachable += 1
            # Best-effort: still emit v so the trace doesn't lose this anchor.
            if out[-1] != v:
                out.append(v)
            continue
        # sub starts at u; skip if already there
        if out[-1] == u:
            out.extend(sub[1:])
        else:
            out.extend(sub)
    # Final dedup pass for consecutive duplicates
    deduped: list[int] = []
    for n in out:
        if not deduped or deduped[-1] != n:
            deduped.append(n)
    return deduped, unreachable


def map_match_hmm(
    coords: list[tuple[float, float]],
    graph,
    *,
    waypoint_step_m: float = 30.0,
    obs_noise_m: float = 50.0,
    max_dist_m: float = 200.0,
    min_prob_norm: float = 0.0001,
    non_emitting_states: bool = True,
    avoid_goingback: bool = True,
) -> MatchedRoute:
    """Hidden Markov Model map-match (Newson-Krumm via ``leuvenmapmatching``).

    Algorithm — given an observation sequence (the projected cartoon polyline)
    and a road graph:

      * **States** are directed graph edges. ``leuvenmapmatching`` enumerates
        edges within ``max_dist_m`` of each observation as candidate states.
      * **Emission probability** ``∝ exp(-d² / 2σ²)`` where ``d`` is the
        observation's distance to the edge centreline and ``σ = obs_noise_m``.
        On cartoon projections the per-point error is well above standard
        GPS noise (20m) — we default to **50m**, with the sweep harness
        exercising {20, 50, 100, 150}.
      * **Transition probability** penalises the mismatch between the
        great-circle distance ``|obs_{i+1} - obs_i|`` and the network
        distance along edges. The library handles this internally; we
        only tune ``avoid_goingback`` (turns off back-tracking that
        artificially fits the noise).
      * **Viterbi decode** returns the globally most-likely edge sequence
        — re-deciding ambiguous early observations once later ones
        disambiguate them. This is the fix the Phase 4b handoff asked
        for: an early waypoint near a forked junction no longer locks
        the entire trace into the wrong corridor.

    We feed downsampled waypoints (same step as Dijkstra path) so the
    Viterbi runtime stays bounded. After the match, we stitch the matched
    node sequence into a graph walk via ``nx.shortest_path`` between any
    non-adjacent neighbours — the same trick the Dijkstra path uses to
    produce a continuous output polyline.

    Defaults are tuned for the cartoon-projection use case, not raw GPS.
    Callers can override via kwargs.

    Returns a :class:`MatchedRoute` with ``mode="hmm"`` and
    ``hmm_states_emitted`` / ``hmm_unreachable_stitches`` populated.
    Raises nothing — failure modes are reported in the returned struct.
    """
    if len(coords) < 2:
        return MatchedRoute(
            coords=list(coords), node_ids=[], length_m=0.0,
            waypoints_used=len(coords), snapped_pairs=0,
            unreachable_segments=0, mode="hmm",
        )

    waypoints = downsample_by_distance(coords, step_m=waypoint_step_m)
    if len(waypoints) < 2:
        return MatchedRoute(
            coords=list(waypoints), node_ids=[], length_m=0.0,
            waypoints_used=len(waypoints), snapped_pairs=0,
            unreachable_segments=0, mode="hmm",
        )

    from leuvenmapmatching.matcher.distance import DistanceMatcher

    imap = _build_inmem_map(graph)
    matcher = DistanceMatcher(
        imap,
        max_dist=max_dist_m,
        max_dist_init=max_dist_m,
        obs_noise=obs_noise_m,
        min_prob_norm=min_prob_norm,
        non_emitting_states=non_emitting_states,
        avoid_goingback=avoid_goingback,
    )
    try:
        states, last_idx = matcher.match(waypoints)
    except Exception as exc:                                       # noqa: BLE001
        logger.warning("hmm matcher failed: %r — returning empty match", exc)
        return MatchedRoute(
            coords=[], node_ids=[], length_m=0.0,
            waypoints_used=len(waypoints), snapped_pairs=0,
            unreachable_segments=1, mode="hmm",
        )

    # Distinct matched edges (preserving order) for diagnostics
    distinct_edges: list[tuple[int, int]] = []
    for s in states:
        if not distinct_edges or distinct_edges[-1] != s:
            distinct_edges.append(s)

    node_seq = list(matcher.path_pred_onlynodes)
    node_path, stitch_unreachable = _stitch_node_path(graph, node_seq)
    snapped_coords = [_node_xy(graph, n) for n in node_path]
    length = _path_length_m(graph, node_path)
    return MatchedRoute(
        coords=snapped_coords,
        node_ids=node_path,
        length_m=length,
        waypoints_used=len(waypoints),
        snapped_pairs=max(0, last_idx),
        unreachable_segments=stitch_unreachable,
        mode="hmm",
        hmm_states_emitted=len(distinct_edges),
        hmm_unreachable_stitches=stitch_unreachable,
    )


def map_match_dispatch(
    coords: list[tuple[float, float]],
    graph,
    *,
    mode: str = "dijkstra",
    waypoint_step_m: float = 30.0,
    # Dijkstra-mode knobs
    k_shortest_paths: int = 1,
    rerank: str = "shape",
    via_nodes: list[tuple[float, float, int]] | None = None,
    # HMM-mode knobs
    hmm_obs_noise_m: float = 50.0,
    hmm_max_dist_m: float = 200.0,
    hmm_min_prob_norm: float = 0.0001,
    hmm_non_emitting_states: bool = True,
    hmm_avoid_goingback: bool = True,
) -> MatchedRoute:
    """Thin dispatch wrapper: pick the matcher by ``mode`` and forward.

    Default ``mode="dijkstra"`` reproduces the legacy ``map_match`` call
    exactly — every existing test/caller is unaffected. ``mode="hmm"``
    routes to the Newson-Krumm matcher above.
    """
    if mode == "hmm":
        return map_match_hmm(
            coords, graph,
            waypoint_step_m=waypoint_step_m,
            obs_noise_m=hmm_obs_noise_m,
            max_dist_m=hmm_max_dist_m,
            min_prob_norm=hmm_min_prob_norm,
            non_emitting_states=hmm_non_emitting_states,
            avoid_goingback=hmm_avoid_goingback,
        )
    if mode != "dijkstra":
        raise ValueError(f"unknown mapmatch mode: {mode!r}")
    return map_match(
        coords, graph,
        waypoint_step_m=waypoint_step_m,
        k_shortest_paths=k_shortest_paths,
        rerank=rerank,
        via_nodes=via_nodes,
    )
