"""Project a normalized shape onto a map and route it through OSRM.

The pipeline is: take an outline in arbitrary (x, y) units, scale it so its
"size" maps to a target on-the-ground distance, project to (lat, lon) around a
center point, ask OSRM to route through the resulting waypoints, and rescale
1-2 more times if the routed distance overshoots/undershoots the target.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple, Union

from fidelity import fidelity_score
from osrm_client import RouteResult, route_through
from shape_utils import Point, bounding_box, outline_perimeter, resample

EARTH_M_PER_DEG_LAT = 111_320.0


@dataclass
class GeneratedRoute:
    waypoints: List[Tuple[float, float]]   # the snapped pig-shape waypoints (lat, lon)
    polyline: List[Tuple[float, float]]    # full street-level polyline (lat, lon)
    distance_m: float
    scale_m_per_unit: float
    center_lat: float = 0.0
    center_lon: float = 0.0
    fidelity: float = float("inf")        # lower is better; see fidelity.py
    # Phase-2 search adds the candidate that won and the per-metric breakdown.
    rotation_deg: float = 0.0
    best_params: dict | None = None
    fidelity_breakdown: dict | None = None


def m_per_deg_lon(lat_deg: float) -> float:
    return EARTH_M_PER_DEG_LAT * math.cos(math.radians(lat_deg))


def project_shape(
    outline: List[Point],
    center_lat: float,
    center_lon: float,
    scale_m_per_unit: float,
) -> List[Tuple[float, float]]:
    """Convert shape (x, y) units to (lat, lon) around the given center.

    The shape is centered on its bounding box so center_lat/lon end up at the
    middle of the pig.
    """
    min_x, min_y, max_x, max_y = bounding_box(outline)
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2

    m_per_lon = m_per_deg_lon(center_lat)
    waypoints: List[Tuple[float, float]] = []
    for x, y in outline:
        dx_m = (x - cx) * scale_m_per_unit
        dy_m = (y - cy) * scale_m_per_unit
        d_lat = dy_m / EARTH_M_PER_DEG_LAT
        d_lon = dx_m / m_per_lon
        waypoints.append((center_lat + d_lat, center_lon + d_lon))
    return waypoints


def generate(
    outline: List[Point],
    center_lat: float,
    center_lon: float,
    target_distance_m: float,
    n_waypoints: int = 40,
    max_iterations: int = 3,
    verify: Union[bool, str] = True,
) -> GeneratedRoute:
    """Generate a routed pig that targets the desired total distance.

    Strategy: start with a scale that would produce target_distance_m if the
    route exactly followed the shape's perimeter. After each OSRM call, multiply
    the scale by (target / actual) and re-route. Streets rarely permit perfect
    tracing, so we iterate a few times rather than expecting one-shot accuracy.
    """
    sampled = resample(outline, n_waypoints)
    perimeter_units = outline_perimeter(sampled)

    # Initial guess: assume routed distance ≈ 1.3× shape perimeter (street-snap inflation).
    scale = (target_distance_m / 1.3) / perimeter_units

    best: GeneratedRoute | None = None
    best_err = float("inf")
    for i in range(max_iterations):
        waypoints = project_shape(sampled, center_lat, center_lon, scale)
        try:
            result = route_through(waypoints, verify=verify)
        except Exception as e:
            # Late iterations can fail when the scale shrinks waypoints onto
            # parks/water/private land where the OSRM foot graph has no edges.
            # Keep the best previous iteration rather than blowing up.
            print(f"  iter {i + 1}: scale={scale:.2f} m/unit FAILED ({e.__class__.__name__}); "
                  f"stopping with best so far")
            if best is None:
                raise
            break
        ratio = target_distance_m / result.distance_m
        err = abs(result.distance_m - target_distance_m) / target_distance_m
        print(f"  iter {i + 1}: scale={scale:.2f} m/unit, routed={result.distance_m:.0f}m, "
              f"target={target_distance_m:.0f}m, ratio={ratio:.3f}")
        if err < best_err:
            best_err = err
            best = GeneratedRoute(
                waypoints=waypoints,
                polyline=result.coordinates,
                distance_m=result.distance_m,
                scale_m_per_unit=scale,
                center_lat=center_lat,
                center_lon=center_lon,
                fidelity=fidelity_score(waypoints, result.coordinates),
            )
        if err < 0.03:
            break
        # Damped update: sqrt avoids oscillation when many segments are
        # fixed-cost detours that don't scale linearly with the shape.
        scale *= ratio ** 0.5

    assert best is not None
    return best


# --- Fidelity-first search --------------------------------------------------
#
# Instead of asking "what scale produces a 10 km route?" the search version
# asks "where on the map and at what size does this animal trace cleanest?"
# Distance becomes a side-effect; what we minimise is the fidelity score
# (mean nearest-neighbor deviation between snapped route and idealized
# outline, normalised by the shape's bounding-box diagonal).


def candidate_centers(center_lat: float,
                      center_lon: float,
                      radius_km: float,
                      n: int) -> List[Tuple[float, float]]:
    """N (lat, lon) candidates: the seed center plus n-1 evenly-spaced
    points on a ring at radius_km/2 km. n=1 returns just the seed."""
    if n <= 1:
        return [(center_lat, center_lon)]
    out = [(center_lat, center_lon)]
    ring_radius_km = max(radius_km / 2.0, 0.0)
    if ring_radius_km == 0.0:
        return out
    d_lat_per_km = 1.0 / 111.32
    d_lon_per_km = 1.0 / (111.32 * math.cos(math.radians(center_lat)))
    for i in range(n - 1):
        theta = 2 * math.pi * i / (n - 1)
        out.append((
            center_lat + ring_radius_km * math.sin(theta) * d_lat_per_km,
            center_lon + ring_radius_km * math.cos(theta) * d_lon_per_km,
        ))
    return out


def candidate_scales(target_distance_m: float,
                     perimeter_units: float,
                     n: int) -> List[float]:
    """N geometrically-spaced scales (m/unit) bracketing the scale that
    would produce target_distance_m if the route exactly followed the
    shape perimeter. The 1.3x inflation factor matches typical
    street-snap behaviour.

    Range spans 0.6x to 3.0x of the base — empirically, fidelity
    improves with scale (each animal feature needs to span multiple city
    blocks to read), so we want to probe well above the user's nominal
    target distance.
    """
    base = (target_distance_m / 1.3) / perimeter_units
    if n <= 1:
        return [base]
    factors = [0.6 * (3.0 / 0.6) ** (i / (n - 1)) for i in range(n)]
    return [base * f for f in factors]


def generate_search(
    outline: List[Point],
    center_lat: float,
    center_lon: float,
    target_distance_m: float = 10_000.0,
    search_radius_km: float = 30.0,
    n_candidates: int = 5,
    n_scales: int = 3,
    n_waypoints: int = 40,
    verify: Union[bool, str] = True,
) -> GeneratedRoute:
    """Search candidate (center, scale) pairs and return the route with the
    best shape fidelity score. Distance is treated as a hint, not a target —
    `target_distance_m` only seeds the scale grid.

    Total OSRM calls: n_candidates × n_scales. With the 1.1s/call rate
    limit, a 5×3 grid takes ~17s; a 9×4 grid ~40s. Prefer fewer candidates
    for interactive use, more for offline sample regeneration.
    """
    if n_candidates < 1 or n_scales < 1:
        raise ValueError("n_candidates and n_scales must be >= 1")

    sampled = resample(outline, n_waypoints)
    perimeter_units = outline_perimeter(sampled)
    centers = candidate_centers(center_lat, center_lon, search_radius_km, n_candidates)
    scales = candidate_scales(target_distance_m, perimeter_units, n_scales)

    best: GeneratedRoute | None = None
    print(f"  fidelity search: {len(centers)} centers × {len(scales)} scales = {len(centers) * len(scales)} candidates")
    for ci, (lat, lon) in enumerate(centers):
        for si, scale in enumerate(scales):
            try:
                waypoints = project_shape(sampled, lat, lon, scale)
                result = route_through(waypoints, verify=verify)
            except Exception as e:
                print(f"    cand {ci+1}/{len(centers)} scale {si+1}/{len(scales)} "
                      f"@ ({lat:.4f},{lon:.4f}) scale={scale:.0f}m/u FAILED ({e.__class__.__name__})")
                continue
            score = fidelity_score(waypoints, result.coordinates)
            print(f"    cand {ci+1}/{len(centers)} scale {si+1}/{len(scales)} "
                  f"@ ({lat:.4f},{lon:.4f}) scale={scale:.0f}m/u "
                  f"routed={result.distance_m/1000:.1f}km fidelity={score:.4f}")
            if best is None or score < best.fidelity:
                best = GeneratedRoute(
                    waypoints=waypoints,
                    polyline=result.coordinates,
                    distance_m=result.distance_m,
                    scale_m_per_unit=scale,
                    center_lat=lat,
                    center_lon=lon,
                    fidelity=score,
                )

    if best is None:
        raise RuntimeError("Every candidate failed; check connectivity / search radius")
    print(f"  best: ({best.center_lat:.4f},{best.center_lon:.4f}) "
          f"scale={best.scale_m_per_unit:.0f}m/u "
          f"routed={best.distance_m/1000:.2f}km fidelity={best.fidelity:.4f}")
    return best


# --- v2: Waschk & Krüger shape-aware routing on a local OSMnx graph ---------
#
# This is the Phase 1 algorithm: project the outline once, load a single
# walking graph, then route segment-by-segment with a shape-aware Dijkstra
# weight. The legacy `generate()` / `generate_search()` functions above
# remain available as a safety net while the new path bakes in.


# Defaults are non-negotiable per plan §0; never lower these without
# updating the plan first.
V2_DEFAULT_TARGET_DISTANCE_M = 20_000      # 20 km is the sweet spot
V2_DEFAULT_SEARCH_RADIUS_M = 30_000        # 30 km — area in which the SEARCH places candidate centres
V2_MIN_TARGET_DISTANCE_M = 15_000          # below 15 km, shape features stop reading
V2_MAX_TARGET_DISTANCE_M = 30_000
# The graph LOAD radius for a single candidate. The plan's risks table
# (§9) caps this at 15 km per candidate to keep callable-weight Dijkstra
# tractable; the 30 km figure above is the SEARCH radius the candidate
# centres are drawn from.
V2_DEFAULT_GRAPH_RADIUS_M = 15_000
V2_MIN_GRAPH_RADIUS_M = 5_000              # smoke / experiment override floor


def generate_v2(
    outline: List[Point],
    center_lat: float,
    center_lon: float,
    target_distance_m: float = V2_DEFAULT_TARGET_DISTANCE_M,
    *,
    n_waypoints: int = 35,
    search_radius_m: int = V2_DEFAULT_SEARCH_RADIUS_M,
    graph_radius_m: int = V2_DEFAULT_GRAPH_RADIUS_M,
    alpha: float = 1.0,
    beta: float = 0.5,
    gamma: float = 4.0,
    use_cache: bool = True,
) -> GeneratedRoute:
    """Generate a road-snapped animal route with the W-K shape-aware router.

    Pipeline:
      1. Resample the outline to ``n_waypoints`` (default 35 — Phase 2
         will sweep this).
      2. Project the outline onto (lat, lon) at the seed center using
         the same scale heuristic as v1 (perimeter ~ 1.3× shape scale).
      3. Load (or pull from disk cache) a 30 km OSMnx walking graph.
      4. Route segment-by-segment with the Waschk-Krüger weight; the
         router naturally hugs roads that parallel the outline.
      5. Score with the Phase-1 ensemble (Hausdorff + Fréchet + IoU).

    No HTTP calls, no rate limit, no SSL trust dance — everything runs
    against the on-disk cached graph after the first download for the
    area.

    Distance is currently a one-shot heuristic: a single graph search
    per call. Phase 2 wraps this in an Optuna multi-candidate search
    that probes (center, scale, rotation) jointly.
    """
    # Lazy imports so unit tests of older code don't pull in osmnx /
    # similaritymeasures unless they actually exercise v2.
    from fidelity import combined_score
    from osmnx_router import (
        DEFAULT_RADIUS_M,
        load_graph,
        shape_aware_route,
    )

    if not (V2_MIN_TARGET_DISTANCE_M <= target_distance_m <= V2_MAX_TARGET_DISTANCE_M):
        raise ValueError(
            f"target_distance_m={target_distance_m:.0f} outside the "
            f"validated 15-30 km range; see plan §0."
        )
    if search_radius_m < DEFAULT_RADIUS_M:
        raise ValueError(
            f"search_radius_m={search_radius_m} < {DEFAULT_RADIUS_M} (30 km). "
            "Smaller radii systematically fail to produce recognisable routes."
        )
    if graph_radius_m < V2_MIN_GRAPH_RADIUS_M:
        raise ValueError(
            f"graph_radius_m={graph_radius_m} < {V2_MIN_GRAPH_RADIUS_M} "
            "(5 km is the lowest experimental floor for the per-candidate graph)."
        )

    sampled = resample(outline, n_waypoints)
    perimeter_units = outline_perimeter(sampled)
    # Same scale heuristic as v1: target_distance ≈ 1.3 × shape_perimeter.
    scale = (target_distance_m / 1.3) / perimeter_units
    waypoints = project_shape(sampled, center_lat, center_lon, scale)

    G = load_graph(center_lat, center_lon, radius_m=graph_radius_m, use_cache=use_cache)

    result = shape_aware_route(
        G,
        waypoints,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        closed=True,
    )

    if not result.polyline:
        raise RuntimeError(
            "shape_aware_route returned no polyline — outline likely outside "
            "the loaded graph footprint"
        )

    score = combined_score(waypoints, result.polyline)
    return GeneratedRoute(
        waypoints=waypoints,
        polyline=result.polyline,
        distance_m=result.distance_m,
        scale_m_per_unit=scale,
        center_lat=center_lat,
        center_lon=center_lon,
        fidelity=score,
    )


# --- v2 search: Optuna TPE over (offset, scale, rotation) -------------------
#
# Pattern lifted from `dsleo/stravart/optimizers.py`: a TPE sampler with a
# uniform startup phase, a multi-metric objective (combined_score), a
# distance soft-penalty, and an early-stop callback. The graph is loaded
# once and reused across every trial — disk cache catches the cold start;
# in-memory reuse catches every subsequent trial.


def _rotate_xy(points: List[Point], theta_rad: float) -> List[Point]:
    """Rotate (x, y) points around the origin by theta_rad radians."""
    c, s = math.cos(theta_rad), math.sin(theta_rad)
    return [(x * c - y * s, x * s + y * c) for x, y in points]


def _distance_adjusted_score(
    fidelity: float,
    route_distance_m: float,
    target_distance_m: float,
    *,
    soft_weight: float = 0.3,
    hard_cap_factor: float = 2.0,
) -> float:
    """Add a distance soft-penalty to the fidelity score; return inf above
    the hard cap. Mirrors the formula in plan §3.5."""
    if route_distance_m > hard_cap_factor * target_distance_m:
        return float("inf")
    err = abs(route_distance_m - target_distance_m) / max(target_distance_m, 1.0)
    return fidelity + soft_weight * err


def generate_search_v2(
    outline: List[Point],
    center_lat: float,
    center_lon: float,
    target_distance_m: float = V2_DEFAULT_TARGET_DISTANCE_M,
    *,
    n_trials: int = 100,
    timeout_s: float | None = 120.0,
    n_startup_trials: int = 20,
    early_stop_score: float = 0.04,
    n_waypoints: int = 35,
    search_radius_m: int = V2_DEFAULT_SEARCH_RADIUS_M,
    graph_radius_m: int = V2_DEFAULT_GRAPH_RADIUS_M,
    alpha: float = 1.0,
    beta: float = 0.5,
    gamma: float = 4.0,
    use_cache: bool = True,
    seed: int | None = 42,
    use_prescreener: bool = True,
    graph=None,
) -> GeneratedRoute:
    """Optuna TPE search over (offset_lat, offset_lon, scale, rotation).

    The objective at each trial:
      1. Sample offsets, scale, rotation
      2. Project the outline through (offset → rotate → scale)
      3. Run W-K shape_aware_route on the cached graph
      4. Score with `combined_score` and add a distance soft-penalty
      5. Reject candidates that violate the prescreener (graph-level)
         or the hard distance cap

    The graph is loaded once and pinned across all trials. ``early_stop_score``
    triggers ``study.stop()`` from a callback when any trial dips below
    it. ``timeout_s`` enforces a wall-clock budget independent of n_trials.

    Pass ``graph=`` to inject a pre-loaded graph (used by tests to avoid
    live OSM downloads).
    """
    import optuna

    if not (V2_MIN_TARGET_DISTANCE_M <= target_distance_m <= V2_MAX_TARGET_DISTANCE_M):
        raise ValueError(
            f"target_distance_m={target_distance_m:.0f} outside the "
            f"validated 15-30 km range; see plan §0."
        )

    from fidelity import combined_score
    from grid_prescreener import prescreen
    from osmnx_router import (
        DEFAULT_RADIUS_M,
        load_graph,
        shape_aware_route,
    )

    if search_radius_m < DEFAULT_RADIUS_M:
        raise ValueError(
            f"search_radius_m={search_radius_m} < {DEFAULT_RADIUS_M} (30 km)."
        )
    if graph_radius_m < V2_MIN_GRAPH_RADIUS_M:
        raise ValueError(
            f"graph_radius_m={graph_radius_m} < {V2_MIN_GRAPH_RADIUS_M}."
        )

    sampled = resample(outline, n_waypoints)
    perimeter_units = outline_perimeter(sampled)
    base_scale = (target_distance_m / 1.3) / perimeter_units

    G = graph if graph is not None else load_graph(
        center_lat, center_lon, radius_m=graph_radius_m, use_cache=use_cache
    )

    # Whole-graph prescreen — if the area itself is hopeless, every trial
    # would just waste compute. Surface the diagnosis instead of failing
    # silently downstream.
    if use_prescreener:
        ok, info = prescreen(G)
        if not ok:
            raise RuntimeError(
                f"Area failed grid prescreener ({info['rejected_for']}): {info}"
            )

    best_state = {"route": None, "params": None, "score": float("inf"),
                  "breakdown": None, "n_pruned": 0}

    def objective(trial: "optuna.Trial") -> float:
        offset_lat = trial.suggest_float("offset_lat", -0.15, 0.15)
        offset_lon = trial.suggest_float("offset_lon", -0.15, 0.15)
        scale_factor = trial.suggest_float("scale_factor", 0.5, 3.0, log=True)
        rotation_deg = trial.suggest_float("rotation_deg", 0.0, 360.0)

        scale = base_scale * scale_factor
        rotated = _rotate_xy(sampled, math.radians(rotation_deg))
        lat = center_lat + offset_lat
        lon = center_lon + offset_lon
        waypoints = project_shape(rotated, lat, lon, scale)

        try:
            r = shape_aware_route(G, waypoints,
                                  alpha=alpha, beta=beta, gamma=gamma,
                                  closed=True)
        except Exception:
            best_state["n_pruned"] += 1
            raise optuna.TrialPruned()

        if not r.polyline:
            best_state["n_pruned"] += 1
            raise optuna.TrialPruned()

        fid, breakdown = combined_score(waypoints, r.polyline,
                                        return_breakdown=True)
        score = _distance_adjusted_score(fid, r.distance_m, target_distance_m)
        if not math.isfinite(score):
            raise optuna.TrialPruned()

        # Track the best by raw distance-adjusted score for return value.
        if score < best_state["score"]:
            best_state["route"] = (waypoints, r, scale, lat, lon, rotation_deg)
            best_state["params"] = dict(trial.params)
            best_state["score"] = score
            best_state["breakdown"] = breakdown
        return score

    def _early_stop(study: "optuna.Study", trial: "optuna.FrozenTrial") -> None:
        if (trial.value is not None and math.isfinite(trial.value)
                and trial.value < early_stop_score):
            study.stop()

    sampler = optuna.samplers.TPESampler(n_startup_trials=n_startup_trials, seed=seed)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, timeout=timeout_s,
                   callbacks=[_early_stop],
                   show_progress_bar=False,
                   catch=(Exception,))

    if best_state["route"] is None:
        raise RuntimeError(
            f"All {n_trials} trials failed (pruned={best_state['n_pruned']}); "
            "check graph connectivity or distance bounds."
        )

    waypoints, r, scale, lat, lon, rot = best_state["route"]
    return GeneratedRoute(
        waypoints=waypoints,
        polyline=r.polyline,
        distance_m=r.distance_m,
        scale_m_per_unit=scale,
        center_lat=lat,
        center_lon=lon,
        fidelity=best_state["score"],
        rotation_deg=rot,
        best_params=best_state["params"],
        fidelity_breakdown=best_state["breakdown"],
    )
