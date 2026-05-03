"""Area-based fidelity scoring.

The question we score: does the routed polyline trace the same area as
the target outline? We answer it in projected meters (equirectangular)
to keep `Polygon.area` interpretable.

Two scores:
- `symmetric_diff_score`: |target XOR route_polygon| / |target|.
  0 means perfect overlap, growing without bound for misses. Best for
  comparing different placements of the SAME template.
- `buffered_iou`: |target ∩ buf(route)| / |target ∪ buf(route)|.
  In [0, 1], higher is better. Buffer of ~80m treats nearby roads
  as 'on' the outline. Best when the route is a polyline rather than
  a closed ring.

We expose both. The search uses `buffered_iou` because the routed
polyline is not always a clean closed polygon — buffering forgives
small gaps and self-intersections.
"""

from __future__ import annotations

import math
from typing import List, Tuple

from shapely.geometry import LineString, Polygon
from shapely.validation import make_valid

_R = 6_371_000.0


def latlon_to_xy(
    coords: List[Tuple[float, float]],
    ref_lat: float,
    ref_lon: float,
) -> List[Tuple[float, float]]:
    """Equirectangular projection to local meters around (ref_lat, ref_lon)."""
    m_per_deg_lat = _R * math.pi / 180.0
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(ref_lat))
    return [
        ((lon - ref_lon) * m_per_deg_lon, (lat - ref_lat) * m_per_deg_lat)
        for lat, lon in coords
    ]


def _polygon_from_closed(coords_xy: List[Tuple[float, float]]) -> Polygon:
    poly = Polygon(coords_xy)
    if not poly.is_valid:
        poly = make_valid(poly)
        if poly.geom_type == 'GeometryCollection':
            polys = [g for g in poly.geoms if g.geom_type in ('Polygon', 'MultiPolygon')]
            if polys:
                poly = polys[0]
    return poly


def buffered_iou(
    target_latlon: List[Tuple[float, float]],
    route_latlon: List[Tuple[float, float]],
    *,
    ref_lat: float | None = None,
    ref_lon: float | None = None,
    buffer_m: float = 80.0,
) -> float:
    """Buffered IoU between target polygon and buffered route LineString."""
    if not route_latlon or len(route_latlon) < 2:
        return 0.0
    if ref_lat is None:
        ref_lat = target_latlon[0][0]
    if ref_lon is None:
        ref_lon = target_latlon[0][1]

    tgt_xy = latlon_to_xy(target_latlon, ref_lat, ref_lon)
    rte_xy = latlon_to_xy(route_latlon, ref_lat, ref_lon)

    target_poly = _polygon_from_closed(tgt_xy)
    route_buf = LineString(rte_xy).buffer(buffer_m)

    if target_poly.is_empty or route_buf.is_empty:
        return 0.0

    inter = target_poly.intersection(route_buf).area
    union = target_poly.union(route_buf).area
    if union <= 0:
        return 0.0
    return inter / union


def symmetric_diff_score(
    target_latlon: List[Tuple[float, float]],
    route_latlon: List[Tuple[float, float]],
    *,
    ref_lat: float | None = None,
    ref_lon: float | None = None,
) -> float:
    """|target XOR route_closed| / |target|. Lower is better; 0 = perfect."""
    if not route_latlon or len(route_latlon) < 3:
        return float('inf')
    if ref_lat is None:
        ref_lat = target_latlon[0][0]
    if ref_lon is None:
        ref_lon = target_latlon[0][1]

    tgt_xy = latlon_to_xy(target_latlon, ref_lat, ref_lon)
    rte_xy = latlon_to_xy(route_latlon, ref_lat, ref_lon)
    if rte_xy[0] != rte_xy[-1]:
        rte_xy.append(rte_xy[0])

    target_poly = _polygon_from_closed(tgt_xy)
    route_poly = _polygon_from_closed(rte_xy)

    if target_poly.is_empty or route_poly.is_empty or target_poly.area <= 0:
        return float('inf')

    sd = target_poly.symmetric_difference(route_poly).area
    return sd / target_poly.area


def composite_score(
    target_latlon: List[Tuple[float, float]],
    route_latlon: List[Tuple[float, float]],
    route_length_m: float,
    target_distance_m: float,
    *,
    buffer_m: float = 80.0,
    distance_weight: float = 0.25,
    distance_floor_m: float = 800.0,
) -> Tuple[float, float]:
    """Returns (combined_score, iou). Combined is to be MAXIMIZED.

    combined = iou * (1 - distance_weight * |L - L*| / L*)
    Penalizes short-circuit routes (route_length << target) and
    way-too-long detours. Uses a soft cap so the IoU still wins
    when distance is reasonable.
    """
    iou = buffered_iou(
        target_latlon, route_latlon, buffer_m=buffer_m,
    )
    if route_length_m < distance_floor_m:
        return (-1.0, iou)
    err = abs(route_length_m - target_distance_m) / max(target_distance_m, 1.0)
    penalty = min(1.0, distance_weight * err)
    return (iou * (1.0 - penalty), iou)


__all__ = [
    'latlon_to_xy',
    'buffered_iou',
    'symmetric_diff_score',
    'composite_score',
]
