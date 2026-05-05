"""Compare a snapped (street-following) route against the original contour.

The map-matching step in :mod:`stravart.mapmatch` will produce *some* route
even when the input contour is wildly off (it routes from snap-A to snap-B
along whatever streets are nearest). To filter those false positives, we
score the snapped route against the unsnapped projected contour using two
shape similarity measures:

* **Discrete Fréchet distance** (metres) — worst-case
  point-to-curve mismatch. Resists outliers in the curve mid-section but
  is very sensitive to dangling/extra start/end pieces.

* **Buffered area IoU** — buffer both polylines by ``buffer_m`` metres
  and compare the symmetric area-IoU. Forgiving of length differences
  but penalises shape divergence.

Both are computed in a *shared* local Cartesian frame anchored at the
union-bbox centre, so disjoint inputs always score zero (lessons #2 in
``~/.claude/projects/.../memory/lessons.md`` — same trap, same fix).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString


logger = logging.getLogger(__name__)


_EARTH_R_M = 6371000.0


# ---------------------------------------------------------- shared frame

def _shared_origin(*polylines: list[tuple[float, float]]) -> tuple[float, float]:
    """Pick a single (lat0, lon0) anchor that's at the union-bbox centre."""
    pts: list[tuple[float, float]] = []
    for pl in polylines:
        pts.extend(pl)
    if not pts:
        return (0.0, 0.0)
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    return ((min(lats) + max(lats)) / 2.0, (min(lons) + max(lons)) / 2.0)


def _to_local_xy(
    polyline: list[tuple[float, float]],
    *,
    lat0: float,
    lon0: float,
) -> np.ndarray:
    """Project (lat, lon) → (x_m, y_m) at the shared anchor. Returns Nx2."""
    if not polyline:
        return np.empty((0, 2))
    rlat0 = math.radians(lat0)
    arr = np.asarray(polyline, dtype=float)
    lat = arr[:, 0]
    lon = arr[:, 1]
    x = np.radians(lon - lon0) * _EARTH_R_M * math.cos(rlat0)
    y = np.radians(lat - lat0) * _EARTH_R_M
    return np.column_stack([x, y])


# ---------------------------------------------------------- Fréchet

def discrete_frechet_m(
    a: list[tuple[float, float]],
    b: list[tuple[float, float]],
) -> float:
    """Discrete Fréchet distance (metres) between two lat/lon polylines.

    Returns ``inf`` if either polyline is empty. Implementation: the
    classic Eiter-Mannila DP over an N×M memo table of point-to-point
    distances. Quadratic in time; fine for our ~few-hundred-point routes.
    """
    if not a or not b:
        return float("inf")

    lat0, lon0 = _shared_origin(a, b)
    A = _to_local_xy(a, lat0=lat0, lon0=lon0)
    B = _to_local_xy(b, lat0=lat0, lon0=lon0)
    n, m = len(A), len(B)

    # Vectorised pairwise Euclidean distance matrix.
    D = np.linalg.norm(A[:, None, :] - B[None, :, :], axis=2)

    ca = np.full((n, m), -1.0)

    # Iterative DP — recursion would blow the stack on long polylines.
    ca[0, 0] = D[0, 0]
    for i in range(1, n):
        ca[i, 0] = max(ca[i - 1, 0], D[i, 0])
    for j in range(1, m):
        ca[0, j] = max(ca[0, j - 1], D[0, j])
    for i in range(1, n):
        for j in range(1, m):
            ca[i, j] = max(
                min(ca[i - 1, j], ca[i - 1, j - 1], ca[i, j - 1]),
                D[i, j],
            )
    return float(ca[n - 1, m - 1])


# ---------------------------------------------------------- buffered IoU

def buffered_iou(
    a: list[tuple[float, float]],
    b: list[tuple[float, float]],
    *,
    buffer_m: float = 20.0,
) -> float:
    """Symmetric area IoU after buffering both polylines by ``buffer_m`` metres.

    Operates in a shared local Cartesian frame so disjoint inputs score 0.0
    (geographically separate polylines should not "overlap" in this score).
    """
    if not a or not b:
        return 0.0
    if buffer_m <= 0:
        raise ValueError("buffer_m must be > 0")
    lat0, lon0 = _shared_origin(a, b)
    A = _to_local_xy(a, lat0=lat0, lon0=lon0)
    B = _to_local_xy(b, lat0=lat0, lon0=lon0)
    if len(A) < 2 or len(B) < 2:
        return 0.0
    polyA = LineString(A).buffer(buffer_m)
    polyB = LineString(B).buffer(buffer_m)
    if polyA.is_empty or polyB.is_empty:
        return 0.0
    union = polyA.union(polyB).area
    if union <= 0:
        return 0.0
    return float(polyA.intersection(polyB).area / union)


# ---------------------------------------------------------- combined

@dataclass(frozen=True)
class FidelityScore:
    """Bundled shape-comparison metrics."""

    frechet_m: float            # ≤ frechet_threshold_m → "good"
    buffered_iou: float         # 0..1 (1 = identical)
    score: float                # weighted combination, 0..1

    @property
    def passes(self) -> bool:
        return self.score >= 0.6


def fidelity(
    snapped: list[tuple[float, float]],
    target: list[tuple[float, float]],
    *,
    buffer_m: float = 20.0,
    frechet_soft_m: float = 200.0,
) -> FidelityScore:
    """Combine Fréchet + buffered-IoU into a single 0..1 fidelity score.

    Heuristic combination:
        * IoU is the dominant term (60%).
        * Fréchet contributes via a soft ``1 - clip(d / frechet_soft_m)``
          decay (40%). At ``d=0`` it contributes 1.0; at ``d>=frechet_soft_m``
          it contributes 0.0. ``frechet_soft_m=200`` is roughly the width of
          a single city block — much further than that and the snap really
          *did* go somewhere different from the input.
    """
    iou = buffered_iou(snapped, target, buffer_m=buffer_m)
    fr = discrete_frechet_m(snapped, target)
    if math.isinf(fr):
        fr_term = 0.0
    else:
        fr_term = max(0.0, 1.0 - fr / max(frechet_soft_m, 1.0))
    score = max(0.0, min(1.0, 0.6 * iou + 0.4 * fr_term))
    return FidelityScore(frechet_m=fr, buffered_iou=iou, score=score)
