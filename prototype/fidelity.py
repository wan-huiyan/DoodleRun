"""Score how closely a snapped street route resembles its idealized animal outline.

The base score is a scale-normalized, symmetric, mean-nearest-neighbor
distance between two polylines (the "Modified Hausdorff Distance" of
Dubuisson & Jain 1994 — more robust to single-point outliers than the
classical max-min form). Lower is better; 0 would be a perfect tracing.

The Phase-1 ensemble adds two more metrics on top:

- **Discrete Fréchet** via ``similaritymeasures.frechet_dist`` — order-
  preserving, catches "right shape, wrong direction" failures that
  Hausdorff (which is order-blind) misses.
- **Buffered area-IoU** via ``shapely.symmetric_difference`` after a
  per-polyline ``buffer(buffer_m)`` — catches "cut the corner" detours
  that nearest-neighbor metrics never see.

A weighted ensemble (``combined_score``) bundles all three. The
turning-function term (rotation invariance) ships in Phase 2; until
then its weight is held at zero in the ensemble.

Scale normalization (divide by the idealized bounding-box diagonal in
metres) lets us compare candidates at *different* shape sizes.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
import similaritymeasures
from shapely.geometry import LineString

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


# ---------------------------------------------------------------------------
# Phase-1 additions: Fréchet, buffered IoU, combined ensemble
# ---------------------------------------------------------------------------


def _to_local_xy(
    points: List[LatLon],
    origin: Tuple[float, float] | None = None,
) -> np.ndarray:
    """Project (lat, lon) into a metres-scale local Cartesian frame.

    If ``origin`` is provided as a (lat, lon) anchor, the projection
    uses it directly. Otherwise the input's own bounding-box centre is
    used. **Pass a shared origin when you need two polylines to live in
    the same frame** (e.g. for buffered-area IoU); using each polyline's
    own bbox centre puts them on top of each other and breaks the
    metric.

    Returned shape: (N, 2) where columns are (x_east_m, y_north_m).
    """
    if not points:
        return np.zeros((0, 2))
    lats = np.array([p[0] for p in points], dtype=float)
    lons = np.array([p[1] for p in points], dtype=float)
    if origin is None:
        lat0 = (lats.min() + lats.max()) / 2.0
        lon0 = (lons.min() + lons.max()) / 2.0
    else:
        lat0, lon0 = origin
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(lat0))
    x = (lons - lon0) * m_per_deg_lon
    y = (lats - lat0) * m_per_deg_lat
    return np.column_stack([x, y])


def _shared_origin(*polylines: List[LatLon]) -> Tuple[float, float]:
    """Pick a (lat, lon) anchor that sits inside the union bounding box
    of all input polylines. Used to project two polylines into the same
    local-tangent frame for area / shape comparisons."""
    lats: List[float] = []
    lons: List[float] = []
    for poly in polylines:
        for lat, lon in poly:
            lats.append(lat)
            lons.append(lon)
    if not lats:
        return (0.0, 0.0)
    return ((min(lats) + max(lats)) / 2.0, (min(lons) + max(lons)) / 2.0)


def frechet_score(idealized: List[LatLon], snapped: List[LatLon]) -> float:
    """Discrete Fréchet distance, normalised by the idealized polyline's
    bounding-box diagonal.

    Uses ``similaritymeasures.frechet_dist`` on a local-tangent
    projection (so the units are metres). Order-preserving: a snapped
    path that traverses the right region in the wrong sequence will
    score worse than an order-blind metric like MHD.
    """
    if not idealized or not snapped:
        return float("inf")
    diag = bbox_diagonal_m(idealized)
    if diag <= 0:
        return float("inf")
    origin = _shared_origin(idealized, snapped)
    a = _to_local_xy(idealized, origin=origin)
    b = _to_local_xy(snapped, origin=origin)
    return float(similaritymeasures.frechet_dist(a, b)) / diag


def area_iou_score(
    idealized: List[LatLon],
    snapped: List[LatLon],
    buffer_m: float = 50.0,
) -> float:
    """Buffered symmetric-difference IoU — fraction of buffered-shape
    area that is *not* shared between the two polylines.

    Both polylines are projected to local metres, buffered by
    ``buffer_m`` (the apparent width of a city block), and combined via
    Shapely's symmetric_difference / union. Returns a value in [0, 1]
    where 0 = identical buffered footprints, 1 = no overlap. Unlike
    Hausdorff or Fréchet, this catches "cut the corner" detours.
    """
    if not idealized or not snapped or buffer_m <= 0:
        return 1.0
    origin = _shared_origin(idealized, snapped)
    a_xy = _to_local_xy(idealized, origin=origin)
    b_xy = _to_local_xy(snapped, origin=origin)
    if len(a_xy) < 2 or len(b_xy) < 2:
        return 1.0
    poly_a = LineString(a_xy).buffer(buffer_m)
    poly_b = LineString(b_xy).buffer(buffer_m)
    union = poly_a.union(poly_b).area
    if union <= 0:
        return 1.0
    sym_diff = poly_a.symmetric_difference(poly_b).area
    return float(sym_diff / union)


# Default ensemble weights. Turning-function ships in Phase 2 with
# weight 0.15; the other three sum to 0.85 today and 1.0 once turning
# is plugged in. Documented here so callers can override per-call.
DEFAULT_WEIGHTS = {
    "hausdorff": 0.35,
    "frechet": 0.30,
    "area_iou": 0.20,
    "turning": 0.0,    # placeholder for Phase 2
}


def combined_score(
    idealized: List[LatLon],
    snapped: List[LatLon],
    *,
    densify_step_m: float = 25.0,
    buffer_m: float = 50.0,
    weights: dict | None = None,
    return_breakdown: bool = False,
) -> float | Tuple[float, dict]:
    """Weighted ensemble of (MHD, Fréchet, area-IoU). Lower is better.

    The three constituent metrics are already in comparable units
    (normalised distances or unit-bounded ratios), so a simple linear
    blend is fine. Pass ``return_breakdown=True`` to also receive the
    per-metric values for debugging.
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    h = fidelity_score(idealized, snapped, densify_step_m=densify_step_m)
    f = frechet_score(idealized, snapped)
    a = area_iou_score(idealized, snapped, buffer_m=buffer_m)

    score = w["hausdorff"] * h + w["frechet"] * f + w["area_iou"] * a
    if return_breakdown:
        return score, {"hausdorff": h, "frechet": f, "area_iou": a, "weights": w}
    return score
