"""Fidelity metrics for comparing a routed polyline to the target template.

We work in metres on a local equirectangular projection (template was
already normalized to a square in load_animal_templates, then projected to
lat/lon by the search; we re-project here).

Lower is better for Fréchet / Hausdorff. Higher is better for buffered IoU.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
from shapely.geometry import LineString, Polygon


def _ll_to_xy(points_ll: List[Tuple[float, float]], ref_lat: float) -> np.ndarray:
    cos_lat = math.cos(math.radians(ref_lat))
    R = 6_371_008.8
    out = np.empty((len(points_ll), 2))
    for i, (lat, lon) in enumerate(points_ll):
        out[i, 0] = math.radians(lon) * R * cos_lat
        out[i, 1] = math.radians(lat) * R
    return out


def _resample_polyline(pts: np.ndarray, n: int) -> np.ndarray:
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return np.repeat(pts[:1], n, axis=0)
    s = np.linspace(0.0, total, n)
    return np.column_stack([np.interp(s, cum, pts[:, 0]),
                            np.interp(s, cum, pts[:, 1])])


def _normalize_to_unit(pts: np.ndarray) -> np.ndarray:
    mn, mx = pts.min(0), pts.max(0)
    extent = (mx - mn).max()
    if extent <= 0:
        return pts
    return (pts - (mn + mx) / 2.0) / extent


def discrete_frechet(P: np.ndarray, Q: np.ndarray) -> float:
    """Iterative Eiter-Mannila O(NM) discrete Fréchet."""
    n, m = len(P), len(Q)
    # pairwise distance matrix
    D = np.linalg.norm(P[:, None, :] - Q[None, :, :], axis=2)
    ca = np.empty((n, m))
    ca[0, 0] = D[0, 0]
    for i in range(1, n):
        ca[i, 0] = max(ca[i - 1, 0], D[i, 0])
    for j in range(1, m):
        ca[0, j] = max(ca[0, j - 1], D[0, j])
    for i in range(1, n):
        for j in range(1, m):
            ca[i, j] = max(min(ca[i - 1, j], ca[i - 1, j - 1], ca[i, j - 1]), D[i, j])
    return float(ca[n - 1, m - 1])


def modified_hausdorff(P: np.ndarray, Q: np.ndarray) -> float:
    """Mean of (mean nearest-neighbour P→Q, mean Q→P) — robust to outliers."""
    from scipy.spatial import cKDTree
    tQ = cKDTree(Q)
    tP = cKDTree(P)
    dPQ = tQ.query(P)[0].mean()
    dQP = tP.query(Q)[0].mean()
    return (dPQ + dQP) / 2.0


def buffered_iou(P: np.ndarray, Q: np.ndarray, buffer_m: float = 50.0) -> float:
    if len(P) < 2 or len(Q) < 2:
        return 0.0
    a = LineString(P).buffer(buffer_m)
    b = LineString(Q).buffer(buffer_m)
    inter = a.intersection(b).area
    union = a.union(b).area
    if union <= 0:
        return 0.0
    return inter / union


def score_route(
    template_xy_unit: np.ndarray,
    route_ll: List[Tuple[float, float]],
    *,
    n_samples: int = 200,
    buffer_m: float = 60.0,
) -> dict:
    """Compare a normalized template (centered, max-side=1) against a real route.

    Both are resampled to `n_samples`, route is centered+scaled into unit space
    using its own bbox so we measure shape fidelity, not placement error.
    """
    if len(route_ll) < 2:
        return {"frechet": math.inf, "mhd": math.inf, "iou": 0.0, "ok": False}
    ref_lat = sum(p[0] for p in route_ll) / len(route_ll)
    route_xy = _ll_to_xy(route_ll, ref_lat)
    route_xy_unit = _normalize_to_unit(route_xy)

    P = _resample_polyline(template_xy_unit, n_samples)
    Q = _resample_polyline(route_xy_unit, n_samples)

    return {
        "frechet": float(discrete_frechet(P, Q)),
        "mhd": float(modified_hausdorff(P, Q)),
        "iou": float(buffered_iou(P, Q, buffer_m=buffer_m / max(1.0, np.linalg.norm(route_xy.max(0) - route_xy.min(0))))),
        "ok": True,
    }
