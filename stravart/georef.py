"""Georectify a strav.art image: image-pixel coordinates → (lat, lon).

Given:
  * a list of OCR'd street labels each at a known image-pixel position
    (``(x_px, y_px)``), and
  * the same street's geographic location resolved by Phase 2's
    cross-reference layer (``(lat, lon)``),

we have ground control points (GCPs) for an affine transform between
the two coordinate frames. With ≥3 GCPs we can fit a 2D affine; with
≥6 we use a robust least-squares fit that tolerates one or two
mis-matched anchors.

Why not a full perspective / projective transform? Strav.art images are
near-orthographic crops of OSM tile renders, so an affine (translation +
rotation + scale + shear) is more than sufficient and degrades gracefully
when only 3 GCPs are available. A homography would need ≥4 and is
ill-conditioned with our anchor counts.

Why a local Cartesian frame instead of fitting directly in (lat, lon)?
At any non-equatorial latitude the lon→x scale ≠ lat→y scale, so a
linear transform fitted on raw (lat, lon) introduces a systematic
shear. We project to a local equirectangular frame anchored on the
GCP centroid, fit there, then project back when forward-mapping.

The chosen approach mirrors osmnx's "project to a local UTM-like
metric frame for distance work" pattern but without the full UTM
zone selection — the precise projection is irrelevant since we only
need internal consistency for fitting, and we invert it on the way out.

This module is pure-Python + numpy + skimage. No network. The unit
tests synthesise GCPs via a known transform and assert recovery to
sub-pixel accuracy.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
from skimage.measure import ransac
from skimage.transform import AffineTransform


logger = logging.getLogger(__name__)


_EARTH_R_M = 6371000.0


# ----------------------------------------------------------------- frame

def _local_xy(
    lat: float, lon: float,
    *, lat0: float, lon0: float,
) -> tuple[float, float]:
    """Equirectangular projection: (lat, lon) → (x_m, y_m) at anchor (lat0, lon0).

    East is +x, north is +y. The factor ``cos(lat0)`` keeps the lon→x scale
    locally consistent with the lat→y scale. Good to <1 m for spans up to
    a few km — adequate for the 5-30 km strav.art route extents.
    """
    rlat0 = math.radians(lat0)
    x = math.radians(lon - lon0) * _EARTH_R_M * math.cos(rlat0)
    y = math.radians(lat - lat0) * _EARTH_R_M
    return x, y


def _inv_local_xy(
    x: float, y: float,
    *, lat0: float, lon0: float,
) -> tuple[float, float]:
    """Inverse of :func:`_local_xy`."""
    rlat0 = math.radians(lat0)
    lat = lat0 + math.degrees(y / _EARTH_R_M)
    lon = lon0 + math.degrees(x / (_EARTH_R_M * math.cos(rlat0)))
    return lat, lon


# ----------------------------------------------------- public dataclasses

@dataclass(frozen=True)
class GroundControlPoint:
    """One pixel ↔ geographic correspondence."""

    x_px: float
    y_px: float
    lat: float
    lon: float
    label: str = ""           # for diagnostics / dropping outliers
    weight: float = 1.0       # for OCR-confidence-weighted least-squares


@dataclass(frozen=True)
class Georectification:
    """Result of fitting an affine pixel→geo transform.

    ``forward(x_px, y_px)`` projects to (lat, lon).
    ``inverse(lat, lon)``  projects to (x_px, y_px).
    """

    transform: AffineTransform        # pixel → local-metric
    lat0: float                       # local-frame anchor
    lon0: float
    n_anchors: int                    # GCPs used in the fit
    rmse_m: float                     # root-mean-square residual, metres
    max_residual_m: float             # worst-case anchor residual, metres
    dropped_labels: tuple[str, ...]   # GCPs removed as outliers (if any)

    # Convenience methods --------------------------------------------------
    def forward(self, x_px: float, y_px: float) -> tuple[float, float]:
        """Pixel coords → (lat, lon)."""
        xy = self.transform(np.asarray([[x_px, y_px]], dtype=float))[0]
        return _inv_local_xy(xy[0], xy[1], lat0=self.lat0, lon0=self.lon0)

    def forward_many(
        self, pixels: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        """Vectorised pixel→geo for a polyline."""
        if not pixels:
            return []
        arr = np.asarray(pixels, dtype=float)
        xy = self.transform(arr)
        return [
            _inv_local_xy(float(x), float(y), lat0=self.lat0, lon0=self.lon0)
            for x, y in xy
        ]

    def inverse(self, lat: float, lon: float) -> tuple[float, float]:
        """(lat, lon) → pixel coords."""
        x_m, y_m = _local_xy(lat, lon, lat0=self.lat0, lon0=self.lon0)
        inv = self.transform.inverse(np.asarray([[x_m, y_m]], dtype=float))[0]
        return float(inv[0]), float(inv[1])


# --------------------------------------------------------------- fitting

def _residuals_m(
    transform: AffineTransform,
    gcps: list[GroundControlPoint],
    *, lat0: float, lon0: float,
) -> np.ndarray:
    """Per-GCP residual distance in metres after applying the transform."""
    if not gcps:
        return np.empty(0)
    px = np.asarray([[g.x_px, g.y_px] for g in gcps], dtype=float)
    target = np.asarray(
        [_local_xy(g.lat, g.lon, lat0=lat0, lon0=lon0) for g in gcps],
        dtype=float,
    )
    pred = transform(px)
    return np.linalg.norm(pred - target, axis=1)


def fit_affine(
    gcps: list[GroundControlPoint],
    *,
    drop_outliers: bool = True,
    ransac_threshold_m: float = 50.0,
    ransac_min_samples: int = 3,
    ransac_max_trials: int = 200,
    min_anchors: int = 3,
) -> Georectification:
    """Fit a 2D affine pixel → local-metric → geographic transform.

    Steps:
        1. Anchor a local equirectangular frame at the GCP centroid (the
           arithmetic mean of GCP lat/lons). This keeps the frame near the
           image and makes the fitted transform numerically well-conditioned.
        2. Stack source = (x_px, y_px) and target = (x_m, y_m); call
           ``skimage.transform.AffineTransform.from_estimate``. With ≥3 GCPs
           skimage solves a 6-DOF least-squares problem.
        3. With ``drop_outliers=True`` and ≥6 GCPs, use RANSAC to pick the
           consensus subset whose pairwise residuals stay within
           ``ransac_threshold_m`` metres. Necessary because Nominatim's
           top-40 sometimes returns the *wrong city's* same-named street,
           and a single such hit at a few km offset can pull the
           least-squares fit away from the inlier consensus by enough to
           hide the bad anchor under a global RMSE threshold.

    Raises ``ValueError`` when fewer than ``min_anchors`` distinct anchors
    are supplied — the caller should treat that as low-confidence and skip.
    """
    if len(gcps) < min_anchors:
        raise ValueError(
            f"need ≥{min_anchors} GCPs to fit an affine, got {len(gcps)}"
        )

    # 1. Local frame
    lat0 = sum(g.lat for g in gcps) / len(gcps)
    lon0 = sum(g.lon for g in gcps) / len(gcps)

    def _solve(gcps_subset: list[GroundControlPoint]) -> AffineTransform:
        src = np.asarray([[g.x_px, g.y_px] for g in gcps_subset], dtype=float)
        dst = np.asarray(
            [_local_xy(g.lat, g.lon, lat0=lat0, lon0=lon0) for g in gcps_subset],
            dtype=float,
        )
        # skimage 0.26+ deprecated the in-place .estimate() in favour of
        # the `from_estimate` class-method, which returns the transform
        # (or False on failure).
        tf = AffineTransform.from_estimate(src, dst)
        if tf is False or tf is None:
            raise ValueError("affine fit did not converge")
        return tf

    dropped: list[str] = []
    # 2. RANSAC consensus filter when we have enough GCPs to spare.
    #    A single mis-hit anchor can sit geometrically central (inside the
    #    convex hull of the inliers) and pull the least-squares fit toward
    #    itself by enough to make the inliers look worse than the outlier
    #    when residuals are ranked. RANSAC samples 3-anchor minimal sets,
    #    counts how many other anchors are within ``ransac_threshold_m``
    #    of the implied transform, and keeps the largest consensus set.
    if drop_outliers and len(gcps) > ransac_min_samples:
        src = np.asarray([[g.x_px, g.y_px] for g in gcps], dtype=float)
        dst = np.asarray(
            [_local_xy(g.lat, g.lon, lat0=lat0, lon0=lon0) for g in gcps],
            dtype=float,
        )
        try:
            model, inliers = ransac(
                (src, dst),
                AffineTransform,
                min_samples=ransac_min_samples,
                residual_threshold=ransac_threshold_m,
                max_trials=ransac_max_trials,
            )
        except Exception:                                         # noqa: BLE001
            model, inliers = None, None
        if model is not None and inliers is not None and inliers.sum() >= min_anchors:
            kept = [g for g, k in zip(gcps, inliers) if k]
            dropped = [g.label for g, k in zip(gcps, inliers) if not k]
            gcps = kept
            tf = _solve(gcps)
        else:
            tf = _solve(gcps)
    else:
        tf = _solve(gcps)

    res = _residuals_m(tf, gcps, lat0=lat0, lon0=lon0)

    rmse = float(np.sqrt(np.mean(res ** 2))) if res.size else 0.0
    max_r = float(np.max(res)) if res.size else 0.0
    return Georectification(
        transform=tf,
        lat0=lat0,
        lon0=lon0,
        n_anchors=len(gcps),
        rmse_m=rmse,
        max_residual_m=max_r,
        dropped_labels=tuple(dropped),
    )


# -------------------------------------------------------- bbox utilities

def project_polyline(
    georef: Georectification,
    pixels: list[tuple[int, int]],
) -> list[tuple[float, float]]:
    """Apply the georef forward transform to a polyline of ints."""
    return georef.forward_many([(float(x), float(y)) for x, y in pixels])


def bbox_of_geocoords(
    coords: list[tuple[float, float]],
    *, pad_m: float = 200.0,
) -> tuple[float, float, float, float]:
    """Padded geographic bbox for a polyline. Returns (S, N, W, E) in degrees.

    ``pad_m`` extends the bbox outward by an isotropic metric distance so
    the OSM graph fetched by the map-matching step contains some context
    around the stroke.
    """
    if not coords:
        raise ValueError("empty coords list")
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)
    if pad_m > 0:
        # 1° latitude ≈ 111 km. 1° longitude depends on cos(lat).
        dlat = pad_m / 111_000.0
        rlat = math.radians((lat_min + lat_max) / 2.0)
        dlon = pad_m / (111_000.0 * max(math.cos(rlat), 1e-6))
        lat_min -= dlat
        lat_max += dlat
        lon_min -= dlon
        lon_max += dlon
    return (lat_min, lat_max, lon_min, lon_max)
