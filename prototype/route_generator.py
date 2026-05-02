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

from osrm_client import RouteResult, route_through
from pig_shape import Point, bounding_box, outline_perimeter, resample

EARTH_M_PER_DEG_LAT = 111_320.0


@dataclass
class GeneratedRoute:
    waypoints: List[Tuple[float, float]]   # the snapped pig-shape waypoints (lat, lon)
    polyline: List[Tuple[float, float]]    # full street-level polyline (lat, lon)
    distance_m: float
    scale_m_per_unit: float


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
        result = route_through(waypoints, verify=verify)
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
            )
        if err < 0.03:
            break
        # Damped update: sqrt avoids oscillation when many segments are
        # fixed-cost detours that don't scale linearly with the shape.
        scale *= ratio ** 0.5

    assert best is not None
    return best
