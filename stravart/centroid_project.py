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
    """Result of a city-scale fallback projection.

    ``polyline`` is the concatenation of every segment in ``polylines``
    (in source order), for callers that want a single flat list.
    ``polylines`` is the per-segment decomposition, used by GPX export
    to emit multiple track segments so the cartoon's branching shape
    (legs, ears, tail) is preserved instead of being drawn as one
    continuous line that doubles back across itself.
    """

    polyline: list[tuple[float, float]]                    # flat concat
    polylines: list[list[tuple[float, float]]]             # per-segment
    centre_lat: float
    centre_lon: float
    scale_m_per_pixel: float
    bbox_width_m: float
    bbox_height_m: float


def centroid_project_contour(
    contour_pixels: list[tuple[int, int]] | list[list[tuple[int, int]]],
    *,
    city_lat: float,
    city_lon: float,
    scale_m_per_pixel: float | None = None,
    target_width_m: float = 4_000.0,
    image_width: int | None = None,
) -> CentroidProjection:
    """Place pixel contour(s) near a city centroid at a chosen metric scale.

    ``contour_pixels`` may be either:
      * a flat list of ``(x, y)`` tuples — a single polyline; or
      * a list of polylines (list of lists of tuples) — Phase 4b multi-
        segment contours where each segment is a branch (leg, ear, tail)
        of the cartoon. Detected by inspecting the first element.

    All polylines are placed in a **shared coordinate frame**: the bbox
    centre across ALL pixels is anchored at ``(city_lat, city_lon)`` and
    the same ``scale_m_per_pixel`` is applied uniformly. This preserves
    the relative geometry of branches — a 100-pixel leg stays a 100-px
    leg in metric terms.

    Two scale-selection modes:

    * **Explicit** (``scale_m_per_pixel`` set) — use the given scale.
    * **Derived from contour bbox width** (default) — pick the scale that
      makes the shared-bbox width equal ``target_width_m`` metres.

    Returns a :class:`CentroidProjection` with both the concatenated
    ``polyline`` and the per-segment ``polylines`` so GPX export can
    emit each branch as its own track segment.
    """
    if not contour_pixels:
        raise ValueError("empty contour")

    # Normalise the two input shapes to a list of polylines.
    first = contour_pixels[0]
    if isinstance(first, tuple):
        # Flat list of (x, y) tuples
        polylines_in: list[list[tuple[int, int]]] = [list(contour_pixels)]
    else:
        polylines_in = [list(p) for p in contour_pixels if p]
        if not polylines_in:
            raise ValueError("empty contour (no non-empty polylines)")

    # Validate point counts after normalisation
    total_pts = sum(len(p) for p in polylines_in)
    if total_pts < 2:
        raise ValueError("contour needs ≥2 points (across all segments)")

    # Shared bbox across all polylines
    all_xs = [float(px) for p in polylines_in for px, _ in p]
    all_ys = [float(py) for p in polylines_in for _, py in p]
    min_x, max_x = min(all_xs), max(all_xs)
    min_y, max_y = min(all_ys), max(all_ys)
    centre_x = (min_x + max_x) / 2.0
    centre_y = (min_y + max_y) / 2.0
    width_px = max(max_x - min_x, 1.0)
    height_px = max(max_y - min_y, 1.0)

    if scale_m_per_pixel is None:
        scale_m_per_pixel = target_width_m / width_px

    dlat_per_m = math.degrees(1.0 / _EARTH_R_M)
    cos_lat = max(math.cos(math.radians(city_lat)), 1e-6)
    dlon_per_m = math.degrees(1.0 / (_EARTH_R_M * cos_lat))

    def _project(px: int | float, py: int | float) -> tuple[float, float]:
        dx_m = (float(px) - centre_x) * scale_m_per_pixel
        # Image y grows downward; geographic latitude grows north (upward).
        dy_m = (centre_y - float(py)) * scale_m_per_pixel
        lat = city_lat + dy_m * dlat_per_m
        lon = city_lon + dx_m * dlon_per_m
        return lat, lon

    out_polylines: list[list[tuple[float, float]]] = [
        [_project(px, py) for px, py in p] for p in polylines_in
    ]
    flat = [pt for p in out_polylines for pt in p]

    return CentroidProjection(
        polyline=flat,
        polylines=out_polylines,
        centre_lat=city_lat,
        centre_lon=city_lon,
        scale_m_per_pixel=float(scale_m_per_pixel),
        bbox_width_m=float(width_px * scale_m_per_pixel),
        bbox_height_m=float(height_px * scale_m_per_pixel),
    )
