"""Score how closely a snapped street route resembles its idealized animal outline.

The score is a scale-normalized, symmetric, mean-nearest-neighbor distance
between two polylines (the "Modified Hausdorff Distance" of Dubuisson & Jain
1994 — more robust to single-point outliers than the classical max-min
form). Lower is better; 0 would be a perfect tracing.

Scale normalization (divide by the idealized bounding-box diagonal in
metres) lets us compare candidates at *different* shape sizes — a 5 km pig
that's 5% off everywhere scores the same as a 10 km pig that's 5% off
everywhere, even though their absolute deviations differ.
"""

from __future__ import annotations

import math
from typing import List, Tuple

LatLon = Tuple[float, float]
EARTH_R_M = 6_371_008.8


def haversine(a: LatLon, b: LatLon) -> float:
    """Great-circle distance between two (lat, lon) points, in metres."""
    lat1, lon1 = a
    lat2, lon2 = b
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(h))


def bbox_diagonal_m(points: List[LatLon]) -> float:
    """Diagonal of the lat/lon bounding box, in metres."""
    if not points:
        return 0.0
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return haversine((min(lats), min(lons)), (max(lats), max(lons)))


def densify(polyline: List[LatLon], step_m: float) -> List[LatLon]:
    """Interpolate intermediate (lat, lon) points along the polyline so no
    consecutive pair is more than ~step_m apart.

    Used to give the idealized outline a similar resolution to the snapped
    route before computing fidelity — a sparse outline would otherwise
    produce optimistic mean-min distances simply because each idealized
    point is closer to *some* densely-sampled snapped point.
    """
    if not polyline or step_m <= 0:
        return list(polyline)
    out: List[LatLon] = [polyline[0]]
    for a, b in zip(polyline, polyline[1:]):
        d = haversine(a, b)
        if d <= step_m:
            out.append(b)
            continue
        n = math.ceil(d / step_m)
        # Linear interpolation in (lat, lon) is fine for the small distances
        # involved; great-circle interpolation is overkill at city scales.
        for i in range(1, n + 1):
            t = i / n
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _mean_min_distance(src: List[LatLon], dst: List[LatLon]) -> float:
    """For each point in src, take its nearest-neighbor distance into dst,
    then average. O(|src| × |dst|); fine for typical 100–2000 point inputs."""
    if not src or not dst:
        return float("inf")
    total = 0.0
    for s in src:
        best = float("inf")
        for d in dst:
            v = haversine(s, d)
            if v < best:
                best = v
        total += best
    return total / len(src)


def fidelity_score(idealized: List[LatLon],
                   snapped:   List[LatLon],
                   densify_step_m: float = 25.0) -> float:
    """Score how well `snapped` traces `idealized`. Lower is better.

    Returns the average of (mean nearest-neighbor distance in each direction),
    normalised by the idealized bounding-box diagonal. A perfect tracing
    scores 0; a route that runs ~5% of the shape's diagonal away from the
    target on average scores 0.05.

    The idealized outline is densified to ~step_m resolution before scoring,
    so a 40-waypoint outline doesn't unfairly score better than a 200-waypoint
    one purely because of point density.
    """
    if not idealized or not snapped:
        return float("inf")
    diag = bbox_diagonal_m(idealized)
    if diag <= 0:
        return float("inf")
    ideal_dense = densify(idealized, densify_step_m)
    snap_dense = densify(snapped, densify_step_m)
    a_to_b = _mean_min_distance(ideal_dense, snap_dense)
    b_to_a = _mean_min_distance(snap_dense, ideal_dense)
    return 0.5 * (a_to_b + b_to_a) / diag
