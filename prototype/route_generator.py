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

from fidelity import combined_score, fidelity_score
from osrm_client import RouteResult, route_through
from shape_utils import Point, bounding_box, outline_perimeter, resample

EARTH_M_PER_DEG_LAT = 111_320.0


@dataclass
class GeneratedRoute:
    waypoints: List[Tuple[float, float]]   # the snapped shape waypoints (lat, lon)
    polyline: List[Tuple[float, float]]    # full street-level polyline (lat, lon)
    distance_m: float
    scale_m_per_unit: float
    center_lat: float = 0.0
    center_lon: float = 0.0
    fidelity: float = float("inf")        # primary score (Hausdorff). Lower=better.
    # Optional component scores from combined_score(). Populated only when the
    # search loop is used; the deterministic generate() leaves them at None.
    frechet: float | None = None
    iou: float | None = None
    combined: float | None = None


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
                     n: int,
                     low: float = 0.5,
                     high: float = 1.8) -> List[float]:
    """N geometrically-spaced scales (m/unit) bracketing the scale that
    would produce target_distance_m if the route followed the shape
    perimeter (with a 1.3x street-snap inflation factor).

    Default sweep is 0.5x..1.8x of the base — narrowed from the original
    0.6x..3.0x because the distance-budget hard cap (Section 6.2 of the
    overhaul plan) rejects routes above 2x target anyway, so probing
    bigger scales burns OSRM calls on candidates that will be discarded.
    """
    base = (target_distance_m / 1.3) / perimeter_units
    if n <= 1:
        return [base]
    factors = [low * (high / low) ** (i / (n - 1)) for i in range(n)]
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
    *,
    distance_cap_factor: float = 2.0,
    distance_weight: float = 0.3,
    score_weights: Tuple[float, float, float] = (0.5, 0.3, 0.2),
) -> GeneratedRoute:
    """Search candidate (center, scale) pairs and return the route with the
    best combined fidelity-plus-distance score.

    The combined score blends Modified Hausdorff (Section 3.1A), discrete
    Fréchet (3.1A), and buffered IoU (3.1B), then applies a soft penalty
    for routes that deviate from `target_distance_m` and a hard cap at
    `distance_cap_factor × target_distance_m` (Section 6.2). Routes above
    the cap are discarded outright — this prevents the 45–70 km blow-up
    runs that pure fidelity-maximization produced.

    Total OSRM calls: n_candidates × n_scales. With the 1.1s/call rate
    limit, a 5×3 grid takes ~17s; a 9×4 grid ~40s.
    """
    if n_candidates < 1 or n_scales < 1:
        raise ValueError("n_candidates and n_scales must be >= 1")

    sampled = resample(outline, n_waypoints)
    perimeter_units = outline_perimeter(sampled)
    centers = candidate_centers(center_lat, center_lon, search_radius_km, n_candidates)
    scales = candidate_scales(target_distance_m, perimeter_units, n_scales)
    max_distance_m = distance_cap_factor * target_distance_m

    best: GeneratedRoute | None = None
    best_combined = float("inf")
    print(f"  fidelity search: {len(centers)} centers × {len(scales)} scales "
          f"= {len(centers) * len(scales)} candidates "
          f"(target={target_distance_m/1000:.1f}km, cap={max_distance_m/1000:.1f}km)")
    for ci, (lat, lon) in enumerate(centers):
        for si, scale in enumerate(scales):
            try:
                waypoints = project_shape(sampled, lat, lon, scale)
                result = route_through(waypoints, verify=verify)
            except Exception as e:
                print(f"    cand {ci+1}/{len(centers)} scale {si+1}/{len(scales)} "
                      f"@ ({lat:.4f},{lon:.4f}) scale={scale:.0f}m/u "
                      f"FAILED ({e.__class__.__name__})")
                continue
            scores = combined_score(
                waypoints, result.coordinates,
                routed_distance_m=result.distance_m,
                target_distance_m=target_distance_m,
                max_distance_m=max_distance_m,
                weights=score_weights,
                distance_weight=distance_weight,
            )
            cap_marker = " ✗ over cap" if scores["combined"] == float("inf") else ""
            print(f"    cand {ci+1}/{len(centers)} scale {si+1}/{len(scales)} "
                  f"@ ({lat:.4f},{lon:.4f}) scale={scale:.0f}m/u "
                  f"routed={result.distance_m/1000:.1f}km "
                  f"H={scores['hausdorff']:.4f} F={scores['frechet']:.4f} "
                  f"IoU={scores['iou']:.3f} → {scores['combined']:.4f}{cap_marker}")
            if scores["combined"] < best_combined:
                best_combined = scores["combined"]
                best = GeneratedRoute(
                    waypoints=waypoints,
                    polyline=result.coordinates,
                    distance_m=result.distance_m,
                    scale_m_per_unit=scale,
                    center_lat=lat,
                    center_lon=lon,
                    fidelity=scores["hausdorff"],
                    frechet=scores["frechet"],
                    iou=scores["iou"],
                    combined=scores["combined"],
                )

    if best is None:
        raise RuntimeError("Every candidate failed (or all over the distance cap); "
                           "increase --distance, increase search-radius-km, or "
                           "raise distance_cap_factor")
    print(f"  best: ({best.center_lat:.4f},{best.center_lon:.4f}) "
          f"scale={best.scale_m_per_unit:.0f}m/u "
          f"routed={best.distance_m/1000:.2f}km "
          f"H={best.fidelity:.4f} F={best.frechet:.4f} IoU={best.iou:.3f} "
          f"combined={best.combined:.4f}")
    return best
