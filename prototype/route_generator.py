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
