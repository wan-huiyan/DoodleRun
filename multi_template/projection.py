"""Project a normalized 2D template onto lat/lon waypoints.

Template is in unit-bbox space (centered on origin). We pick:
  - center_lat, center_lon: where to drop the shape
  - scale_m: how big to draw it (longest side, in metres)
  - rotation_deg: orientation
  - n_waypoints: how many evenly-spaced template points to keep

Then map each (x, y) → (lat, lon) on a local equirectangular projection.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np


EARTH_M_PER_DEG_LAT = 111_320.0


def _m_per_deg_lon(lat_deg: float) -> float:
    return EARTH_M_PER_DEG_LAT * math.cos(math.radians(lat_deg))


def _resample(pts: np.ndarray, n: int) -> np.ndarray:
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return np.repeat(pts[:1], n, axis=0)
    s = np.linspace(0.0, total, n)
    return np.column_stack([np.interp(s, cum, pts[:, 0]),
                            np.interp(s, cum, pts[:, 1])])


def project_template(
    template_xy: np.ndarray,
    *,
    center_lat: float,
    center_lon: float,
    scale_m: float,
    rotation_deg: float = 0.0,
    n_waypoints: int = 15,
) -> Tuple[List[Tuple[float, float]], np.ndarray]:
    """Return ((lat, lon) waypoints, full lat/lon polyline)."""
    pts = template_xy.copy()
    if rotation_deg:
        a = math.radians(rotation_deg)
        R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        pts = pts @ R.T
    pts = pts * scale_m  # template is in unit-bbox space
    deg_per_m_lat = 1.0 / EARTH_M_PER_DEG_LAT
    deg_per_m_lon = 1.0 / _m_per_deg_lon(center_lat)
    lat = center_lat + pts[:, 1] * deg_per_m_lat
    lon = center_lon + pts[:, 0] * deg_per_m_lon
    full_polyline = np.column_stack([lat, lon])
    # Evenly-spaced waypoints from the dense polyline
    waypoint_xy = _resample(np.column_stack([lat, lon]), n_waypoints)
    waypoints = [(float(la), float(lo)) for la, lo in waypoint_xy]
    return waypoints, full_polyline


def template_in_xy_unit(points: np.ndarray) -> np.ndarray:
    """Already-normalized templates pass through; rebuild for safety."""
    mn, mx = points.min(0), points.max(0)
    extent = (mx - mn).max()
    if extent <= 0:
        return points
    return (points - (mn + mx) / 2.0) / extent
