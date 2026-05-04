"""Rotation-invariant polygon similarity via turning functions.

Implements Arkin et al. (1991) "An efficiently computable metric for
comparing polygonal shapes." A polygon is reduced to its *turning
function* Θ(s): cumulative turning angle as a function of normalised
arc length s ∈ [0, 1]. Two polygons are then compared by the L² distance
between their turning functions, minimised over global rotation θ
(closed-form) and — for closed polygons — over starting-vertex shift t
(O(n²) brute search; the n is already small here, ≤200 vertices).

We ship this in-tree because the canonical PyPI package
(``turning-function``, DBraun) only publishes wheels through Python
3.10 and lacks an sdist on macOS/x86_64. The math below is ~50 lines of
NumPy; writing the wrapper for the missing wheel would have been more
code than the algorithm itself.

Public API:
    turning_distance(poly_a, poly_b, *, closed=True, normalize=True) -> float

`poly_a` / `poly_b` are sequences of (x, y) points in any consistent
unit (we normalise by perimeter). Returns a value in [0, 1] when
`normalize=True` (divides by π — the worst-case turning RMS); raw
radians otherwise.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple

import numpy as np

XY = Tuple[float, float]


# Cap the per-polyline vertex count before scoring. The library §0 alluded to
# a soft cap of ~100; we use 200 here since our outlines plus a max-density
# resample stay well below that on the inputs we care about.
DEFAULT_MAX_POINTS = 200


def _resample_uniform(points: np.ndarray, n: int) -> np.ndarray:
    """Resample a polyline to ``n`` points uniformly along arc length.

    Operates in whatever (x, y) units the caller passes in; we never
    convert to polar so closed polygons are handled the same as open
    polylines.
    """
    if len(points) < 2 or n < 2:
        return points
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return np.repeat(points[:1], n, axis=0)
    targets = np.linspace(0.0, total, n)
    out = np.empty((n, 2))
    out[:, 0] = np.interp(targets, cum, points[:, 0])
    out[:, 1] = np.interp(targets, cum, points[:, 1])
    return out


def _turning_function(points: np.ndarray, closed: bool) -> Tuple[np.ndarray, np.ndarray]:
    """Return (s, theta) where s ∈ [0, 1] is normalised cumulative arc
    length at each vertex and theta is the cumulative *turning* angle
    (radians) at that vertex (theta[0] = 0).

    For a closed polygon, the implicit closing edge is included.
    """
    pts = np.asarray(points, dtype=float)
    if closed and not np.allclose(pts[0], pts[-1]):
        pts = np.vstack([pts, pts[:1]])
    diffs = np.diff(pts, axis=0)
    seg_len = np.linalg.norm(diffs, axis=1)
    bearings = np.arctan2(diffs[:, 1], diffs[:, 0])
    # Cumulative turning angle at each vertex: 0 at start; at vertex i+1 we
    # add the wrapped angle change between segments i and i-1.
    delta = np.diff(bearings)
    delta = np.mod(delta + np.pi, 2 * np.pi) - np.pi
    theta = np.concatenate([[0.0], np.cumsum(delta)])
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = cum[-1]
    if total <= 0:
        return np.zeros(len(theta)), np.zeros(len(theta))
    s = cum / total
    return s, theta


def _piecewise_l2_distance(s_a: np.ndarray, t_a: np.ndarray,
                           s_b: np.ndarray, t_b: np.ndarray,
                           *, theta_offset: float = 0.0) -> float:
    """L² distance between two piecewise-constant turning functions on
    [0, 1] with knots ``s_a`` and ``s_b``.

    The functions are *constant* on each segment (matching the discrete
    polygonal interpretation: turning happens at vertices, not along
    edges). We merge the two knot sets, evaluate each function on every
    sub-interval, and integrate the squared difference closed-form.
    """
    knots = np.unique(np.concatenate([s_a, s_b, [0.0, 1.0]]))
    if len(knots) < 2:
        return 0.0
    mids = (knots[:-1] + knots[1:]) / 2.0
    # Piecewise-constant evaluation — value on (s_i, s_{i+1}) is the turning
    # angle at the latest vertex with s ≤ s_i (for the appropriate poly).
    idx_a = np.clip(np.searchsorted(s_a, mids, side="right") - 1, 0, len(t_a) - 1)
    idx_b = np.clip(np.searchsorted(s_b, mids, side="right") - 1, 0, len(t_b) - 1)
    diff = t_a[idx_a] - t_b[idx_b] - theta_offset
    widths = np.diff(knots)
    return float(np.sqrt(np.sum(diff * diff * widths)))


def _optimal_rotation_offset(s_a: np.ndarray, t_a: np.ndarray,
                             s_b: np.ndarray, t_b: np.ndarray) -> float:
    """Closed-form optimum θ that minimises the L² distance between
    Θ_a(s) and Θ_b(s) + θ. The optimum is the integral of the
    difference (which is just the weighted mean diff over [0, 1])."""
    knots = np.unique(np.concatenate([s_a, s_b, [0.0, 1.0]]))
    mids = (knots[:-1] + knots[1:]) / 2.0
    idx_a = np.clip(np.searchsorted(s_a, mids, side="right") - 1, 0, len(t_a) - 1)
    idx_b = np.clip(np.searchsorted(s_b, mids, side="right") - 1, 0, len(t_b) - 1)
    widths = np.diff(knots)
    return float(np.sum((t_a[idx_a] - t_b[idx_b]) * widths))


def turning_distance(
    poly_a: Sequence[XY],
    poly_b: Sequence[XY],
    *,
    closed: bool = True,
    normalize: bool = True,
    max_points: int = DEFAULT_MAX_POINTS,
    n_phase_shifts: int = 0,
) -> float:
    """Distance between two polygons' turning functions.

    Parameters
    ----------
    poly_a, poly_b
        Sequences of (x, y) points. Same coordinate system; can be in
        any units (results are scale-invariant).
    closed
        Treat both inputs as closed polygons (append the start point).
    normalize
        Divide the L² distance by π (the largest meaningful turning
        magnitude) so the return value lives in [0, 1] for typical
        inputs. Set False to keep raw radians.
    max_points
        Cap the per-polyline vertex count via uniform-arc-length
        resampling. ≥200 produces no resampling on our typical 30-50
        vertex outlines but keeps us safe for densified routes.
    n_phase_shifts
        For closed polygons, also minimise over starting-vertex shifts.
        Set to e.g. 12 to try 12 evenly-spaced starts (3.5x slower but
        catches "right shape, wrong starting vertex" mismatches). The
        default 0 means use the existing start point as canonical (set
        by the caller — usually the first outline waypoint).

    Returns
    -------
    float in [0, 1] when normalize=True, otherwise raw radians.
    """
    if not poly_a or not poly_b:
        return 1.0 if normalize else math.pi
    a = np.asarray(poly_a, dtype=float)
    b = np.asarray(poly_b, dtype=float)
    if len(a) > max_points:
        a = _resample_uniform(a, max_points)
    if len(b) > max_points:
        b = _resample_uniform(b, max_points)
    if len(a) < 3 or len(b) < 3:
        return 1.0 if normalize else math.pi

    s_a, t_a = _turning_function(a, closed)
    s_b, t_b = _turning_function(b, closed)

    def _eval_with_shift(shift_b_by: int) -> float:
        if shift_b_by == 0:
            sb, tb = s_b, t_b
        else:
            # Re-roll polygon b's starting vertex; turning function is
            # recomputed from scratch (cheap on resampled inputs).
            rolled = np.roll(b[:-1] if closed and np.allclose(b[0], b[-1]) else b,
                             -shift_b_by, axis=0)
            sb, tb = _turning_function(rolled, closed)
        offset = _optimal_rotation_offset(s_a, t_a, sb, tb)
        return _piecewise_l2_distance(s_a, t_a, sb, tb, theta_offset=offset)

    if closed and n_phase_shifts > 0:
        n_b = len(b) - (1 if closed and np.allclose(b[0], b[-1]) else 0)
        step = max(1, n_b // n_phase_shifts)
        candidates = [_eval_with_shift(k) for k in range(0, n_b, step)]
        raw = min(candidates) if candidates else _eval_with_shift(0)
    else:
        raw = _eval_with_shift(0)

    if not normalize:
        return raw
    # Dividing by π scales the typical worst case (a snapped path that
    # turns the wrong way at every vertex) onto roughly [0, 1]. Clip to
    # be safe — pathological inputs can exceed π in the L² norm.
    return float(min(1.0, raw / math.pi))
