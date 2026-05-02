"""Score how closely a snapped street route resembles its idealized animal outline.

The primary score (Modified Hausdorff Distance — Dubuisson & Jain 1994) is a
scale-normalized symmetric mean-nearest-neighbor distance between two
polylines. Lower is better; 0 would be a perfect tracing. This file also
exposes:

* `frechet_score()` — discrete Fréchet distance, order-aware and strictly
  better than Hausdorff for "do these polylines trace the same path?"
  (Section 3.1A of the overhaul plan.)
* `iou_score()` — buffered IoU. Penalizes "cut the corner" detours that
  Hausdorff/Fréchet miss because they only look at point-to-point distances.
  (Section 3.1B.)
* `combined_score()` — weighted blend of all three, plus an optional
  distance-deviation penalty with a hard 2x cap for the route generator's
  search loop. (Section 6.2.)

All metrics are normalized by the idealized bounding-box diagonal in metres
so cross-shape and cross-scale comparisons are meaningful.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

LatLon = Tuple[float, float]
EARTH_R_M = 6_371_008.8


# ---- Geodesy ---------------------------------------------------------------

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
    consecutive pair is more than ~step_m apart."""
    if not polyline or step_m <= 0:
        return list(polyline)
    out: List[LatLon] = [polyline[0]]
    for a, b in zip(polyline, polyline[1:]):
        d = haversine(a, b)
        if d <= step_m:
            out.append(b)
            continue
        n = math.ceil(d / step_m)
        for i in range(1, n + 1):
            t = i / n
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


# ---- Local equirectangular projection --------------------------------------
#
# All shape-similarity metrics live in metres-on-the-ground via a quick
# equirectangular projection around the polyline's mean latitude. At
# city scales (a few km) the distortion is well under 1% — fine for
# scoring.

def _project_to_meters(polyline: List[LatLon]) -> Tuple[List[Tuple[float, float]], LatLon]:
    """Project (lat, lon) points to a local (x, y) metres-on-the-ground frame.

    Returns the projected points plus the (lat, lon) origin so the caller
    can also project a second polyline to the same frame.
    """
    if not polyline:
        return [], (0.0, 0.0)
    lat0 = sum(p[0] for p in polyline) / len(polyline)
    lon0 = sum(p[1] for p in polyline) / len(polyline)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))
    out = [
        ((lon - lon0) * m_per_deg_lon, (lat - lat0) * m_per_deg_lat)
        for lat, lon in polyline
    ]
    return out, (lat0, lon0)


def _project_to_origin(polyline: List[LatLon], origin: LatLon) -> List[Tuple[float, float]]:
    """Project to the (x, y) frame anchored at `origin` (lat0, lon0)."""
    lat0, lon0 = origin
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))
    return [
        ((lon - lon0) * m_per_deg_lon, (lat - lat0) * m_per_deg_lat)
        for lat, lon in polyline
    ]


# ---- Modified Hausdorff (existing primary scorer) --------------------------

def _mean_min_distance(src: List[LatLon], dst: List[LatLon]) -> float:
    """Mean of nearest-neighbor distances from src into dst.

    O(|src| × |dst|) brute-force; fine for the 100–2000 point ranges we
    actually feed it (typical shapes densified to 25 m steps).
    """
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
    """Symmetric mean-nearest-neighbor (Modified Hausdorff) distance,
    normalised by the idealized bounding-box diagonal. Lower = better."""
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


# ---- Discrete Fréchet (order-aware) ----------------------------------------

def frechet_score(idealized: List[LatLon],
                  snapped:   List[LatLon],
                  densify_step_m: float = 25.0) -> float:
    """Discrete Fréchet distance, normalized by the idealized bbox diagonal.

    Unlike Hausdorff, Fréchet is order-preserving: a route that traces the
    pig backwards no longer scores the same as one tracing it forwards. We
    fall back to a pure-Python implementation if shapely's
    frechet_distance is unavailable.
    """
    if not idealized or not snapped:
        return float("inf")
    diag = bbox_diagonal_m(idealized)
    if diag <= 0:
        return float("inf")
    ideal_dense = densify(idealized, densify_step_m)
    snap_dense = densify(snapped, densify_step_m)

    try:
        import shapely  # type: ignore
        from shapely.geometry import LineString  # type: ignore
        ideal_xy = _project_to_meters(ideal_dense)[0]
        # Project the snapped polyline to the same origin so distances are
        # in the same frame.
        origin_lat = sum(p[0] for p in ideal_dense) / len(ideal_dense)
        origin_lon = sum(p[1] for p in ideal_dense) / len(ideal_dense)
        snap_xy = _project_to_origin(snap_dense, (origin_lat, origin_lon))
        a = LineString(ideal_xy)
        b = LineString(snap_xy)
        d = shapely.frechet_distance(a, b)
        return float(d) / diag
    except Exception:
        # Pure-Python fallback (O(|p|×|q|) memo; OK for densified inputs of
        # a few hundred points).
        return _frechet_fallback(ideal_dense, snap_dense) / diag


def _frechet_fallback(p: List[LatLon], q: List[LatLon]) -> float:
    if not p or not q:
        return float("inf")
    n, m = len(p), len(q)
    # Iterative DP to avoid 1000-deep recursion on densified inputs.
    ca = [[-1.0] * m for _ in range(n)]
    ca[0][0] = haversine(p[0], q[0])
    for i in range(1, n):
        ca[i][0] = max(ca[i - 1][0], haversine(p[i], q[0]))
    for j in range(1, m):
        ca[0][j] = max(ca[0][j - 1], haversine(p[0], q[j]))
    for i in range(1, n):
        for j in range(1, m):
            ca[i][j] = max(
                min(ca[i - 1][j], ca[i - 1][j - 1], ca[i][j - 1]),
                haversine(p[i], q[j]),
            )
    return ca[n - 1][m - 1]


# ---- Buffered IoU (area-overlap) -------------------------------------------

def iou_score(idealized: List[LatLon],
              snapped:   List[LatLon],
              buffer_m:  float = 30.0) -> float:
    """Buffered intersection-over-union deficit between the two polylines.

    Returns 1 - IoU(buffer(ideal), buffer(snapped)) so it shares the
    "lower = better" convention with the other scorers and lives in [0, 1].

    The 30 m buffer roughly matches a city block's road width — pick
    bigger if you want to be lenient about parallel-road detours, smaller
    for stricter scoring. Catches "cut the corner" detours that Hausdorff
    misses because the snapped route is still close to the outline points
    even when the area shape is wrong.
    """
    if not idealized or not snapped:
        return 1.0
    try:
        from shapely.geometry import LineString  # type: ignore
    except Exception:
        return 0.0  # shapely not available — disable scoring rather than blow up

    ideal_xy, origin = _project_to_meters(idealized)
    snap_xy = _project_to_origin(snapped, origin)
    if len(ideal_xy) < 2 or len(snap_xy) < 2:
        return 1.0
    try:
        a = LineString(ideal_xy).buffer(buffer_m)
        b = LineString(snap_xy).buffer(buffer_m)
        union = a.union(b).area
        if union <= 0:
            return 1.0
        inter = a.intersection(b).area
        return 1.0 - inter / union
    except Exception:
        return 1.0


# ---- Combined scoring (drives the search loop) -----------------------------

def combined_score(
    idealized: List[LatLon],
    snapped: List[LatLon],
    *,
    routed_distance_m: Optional[float] = None,
    target_distance_m: Optional[float] = None,
    max_distance_m: Optional[float] = None,
    weights: Tuple[float, float, float] = (0.5, 0.3, 0.2),
    distance_weight: float = 0.3,
    iou_buffer_m: float = 30.0,
    densify_step_m: float = 25.0,
) -> dict:
    """Compute Hausdorff + Fréchet + buffered-IoU and combine them with an
    optional distance-deviation penalty.

    Returns a dict with the three component scores plus the combined
    score, so callers can log per-component fidelity (useful when tuning
    weights) without recomputing.

    `weights` blends (Hausdorff, Fréchet, IoU). All three are in roughly
    the same [0, 1] range after normalization, so a simple weighted sum
    works. Default 0.5/0.3/0.2 follows the plan's guidance — Hausdorff
    is the most stable baseline; Fréchet adds order-awareness; IoU
    catches shape-collapse pathologies.

    `routed_distance_m` / `target_distance_m` enable the soft penalty.
    `max_distance_m` enables the hard cap (returns +inf above it).
    """
    h = fidelity_score(idealized, snapped, densify_step_m=densify_step_m)
    f = frechet_score(idealized, snapped, densify_step_m=densify_step_m)
    i = iou_score(idealized, snapped, buffer_m=iou_buffer_m)

    wh, wf, wi = weights
    combined = wh * h + wf * f + wi * i

    # Distance budget (Section 6.2 of the plan).
    if (routed_distance_m is not None
            and max_distance_m is not None
            and routed_distance_m > max_distance_m):
        combined = float("inf")
    elif (routed_distance_m is not None and target_distance_m
          and target_distance_m > 0):
        deviation = abs(routed_distance_m - target_distance_m) / target_distance_m
        combined += distance_weight * deviation

    return {
        "hausdorff": h,
        "frechet": f,
        "iou": i,
        "combined": combined,
    }
