"""Phase 4b — centroid-anchored fallback projection for OCR-zero images.

About half of the strav.art catalog renders at "regional zoom" — Berlin
districts, English counties, Dutch boroughs — where the basemap shows
neighbourhood / district labels rather than street labels. EasyOCR
returns 30-60 fragments per such image but none parse as a street name,
so the OCR-anchored pipeline in :mod:`stravart.reconstruct` aborts at
``ocr: no street candidates``.

These images still carry useful information: the **contour shape** is
intact, and Phase 1's title geocoder typically resolved the rough
location (``BERLIN MUTT`` → Berlin centroid). A reconstruction that
places the contour near the title centroid at a fixed metric scale
preserves the shape and gives "see roughly where this run happened".
Geographic fidelity drops from street-scale to city-scale — these
results are *decorative*, not navigable.

The output of this module is consumed by :func:`stravart.reconstruct`
behind a ``kind="city-scale"`` flag so the iOS client can present
city-scale fallbacks differently from runnable street-scale GPX.

Why no per-pixel affine? An affine needs ≥3 GCPs and we have zero.
Why not a fixed-size icon overlay? We want the contour preserved so
the artistic shape (which is the whole point of strav.art) is visible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


_EARTH_R_M = 6_371_000.0


@dataclass(frozen=True)
class CentroidProjection:
    """Result of a city-scale fallback projection."""

    polyline: list[tuple[float, float]]   # (lat, lon) in geographic order
    centre_lat: float
    centre_lon: float
    scale_m_per_pixel: float
    bbox_width_m: float
    bbox_height_m: float


def centroid_project_contour(
    contour_pixels: list[tuple[int, int]],
    *,
    city_lat: float,
    city_lon: float,
    scale_m_per_pixel: float | None = None,
    target_width_m: float = 4_000.0,
    image_width: int | None = None,
) -> CentroidProjection:
    """Place a pixel contour near a city centroid at a chosen metric scale.

    The contour is centred at ``(city_lat, city_lon)`` and scaled
    isotropically. Two scale-selection modes:

    * **Explicit** (``scale_m_per_pixel`` set) — use the given scale. Useful
      when calibrating against a known city extent.
    * **Derived from contour width** (default) — pick the scale that makes
      the contour bbox width equal ``target_width_m`` metres. With the
      typical 4 km default a 600-pixel-wide contour lands as a 4 km run,
      which is in-line with most strav.art route lengths.

    ``image_width`` is accepted for API symmetry with the affine pipeline
    but only used when caller explicitly supplies it; the contour bbox
    alone is sufficient to choose the scale.

    Returns a :class:`CentroidProjection` with the geographic polyline
    and the bbox extents in metres (for downstream sanity checks).
    """
    if not contour_pixels:
        raise ValueError("empty contour")
    if len(contour_pixels) < 2:
        raise ValueError("contour needs ≥2 points")

    xs = [float(x) for x, _ in contour_pixels]
    ys = [float(y) for _, y in contour_pixels]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    centre_x = (min_x + max_x) / 2.0
    centre_y = (min_y + max_y) / 2.0
    width_px = max(max_x - min_x, 1.0)
    height_px = max(max_y - min_y, 1.0)

    if scale_m_per_pixel is None:
        scale_m_per_pixel = target_width_m / width_px

    # Geographic step per metre at this latitude.
    dlat_per_m = math.degrees(1.0 / _EARTH_R_M)
    cos_lat = max(math.cos(math.radians(city_lat)), 1e-6)
    dlon_per_m = math.degrees(1.0 / (_EARTH_R_M * cos_lat))

    polyline: list[tuple[float, float]] = []
    for px, py in contour_pixels:
        dx_m = (float(px) - centre_x) * scale_m_per_pixel
        # Image y grows downward; geographic latitude grows north (upward).
        dy_m = (centre_y - float(py)) * scale_m_per_pixel
        lat = city_lat + dy_m * dlat_per_m
        lon = city_lon + dx_m * dlon_per_m
        polyline.append((lat, lon))

    return CentroidProjection(
        polyline=polyline,
        centre_lat=city_lat,
        centre_lon=city_lon,
        scale_m_per_pixel=float(scale_m_per_pixel),
        bbox_width_m=float(width_px * scale_m_per_pixel),
        bbox_height_m=float(height_px * scale_m_per_pixel),
    )
