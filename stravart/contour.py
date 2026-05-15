"""Extract the drawn route line from a strav.art image.

The strav.art rendering convention: the route is overlaid on a desaturated
basemap using a single saturated colour — red, magenta, pink, orange, or
occasionally blue/purple. Phase 2's ``ocr.route_mask`` already separates "very
saturated" pixels from the basemap; here we build on the same idea but with a
goal of *preserving* the line geometry instead of inpainting it away.

Pipeline:
    1.  HSV mask: high saturation + non-trivial value, restricted to the
        warm-colour wedges that strav.art uses (red 0..30°, magenta/pink
        300..360°, orange 10..40°). This excludes the basemap's faint blues
        and greens, which would otherwise contaminate the trace.
    2.  Morphological close (3px) to seal small gaps from anti-aliasing.
    3.  Largest-component filter — drops the start/end map pins which sit
        as small disconnected blobs.
    4.  Skeletonise to a 1-pixel-wide centreline.
    5.  Trace the skeleton into an ordered polyline (8-connected DFS from
        an endpoint; falls back to a deterministic seed for closed loops).

Output is a list of ``(x, y)`` integer pixel coordinates in image space
(top-left origin, x → column, y → row), ordered from one end of the route
to the other.

This module is intentionally pure CPU + numpy + OpenCV + skimage so the
unit tests can run without OCR / network. ``trace_route`` works on any
binary mask, which makes synthetic-image fixtures easy to construct.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
from skimage.morphology import skeletonize


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- HSV mask

# Hue ranges that capture the strav.art route colours we've seen in the
# corpus. OpenCV uses 0..180 for hue (degrees / 2). Each entry is
# ``(hue_low, hue_high)`` inclusive; entries can wrap past 180/0 by being
# expressed as two ranges around the boundary.
_ROUTE_HUE_BANDS_OCV: tuple[tuple[int, int], ...] = (
    (0, 20),     # red / orange-red (0–40°)
    (160, 180),  # red wrap (320–360°)
    (140, 165),  # magenta / pink (280–330°)
    (10, 25),    # orange (20–50°) — overlaps with red-orange; harmless
)


def route_mask_colored(
    bgr: np.ndarray,
    *,
    sat_min: int = 90,
    val_min: int = 60,
) -> np.ndarray:
    """Binary mask of likely route-line pixels, HSV-colour-restricted.

    ``ocr.route_mask`` thresholds on saturation alone, which is fine for
    inpainting (we want to *erase* every saturated pixel). For Phase 3 we
    want only the route line, so we additionally clip to the warm-colour
    hue bands strav.art uses. This excludes Strava's blue/green per-mile
    pins which would otherwise contaminate the trace.
    """
    if bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError(f"expected BGR ndarray (H,W,3), got shape {bgr.shape}")
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sat_val = (s >= sat_min) & (v >= val_min)

    hue_band = np.zeros_like(h, dtype=bool)
    for lo, hi in _ROUTE_HUE_BANDS_OCV:
        hue_band |= (h >= lo) & (h <= hi)

    return (sat_val & hue_band).astype(np.uint8) * 255


def _largest_component(mask: np.ndarray, *, min_area: int = 200) -> np.ndarray:
    """Return ``mask`` reduced to its largest connected component.

    Strava-style images have several saturated blobs (start pin, finish pin,
    distance markers). Without this filter the skeletonise step builds a
    forest instead of a path.
    """
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask, connectivity=8,
    )
    if n_labels <= 1:
        return mask
    # stats has [bg, comp_1, comp_2, ...]; bg is row 0.
    areas = stats[1:, cv2.CC_STAT_AREA]
    if areas.size == 0:
        return mask
    biggest = int(areas.argmax()) + 1
    biggest_area = int(areas.max())
    if biggest_area < min_area:
        return np.zeros_like(mask)
    return ((labels == biggest).astype(np.uint8)) * 255


def clean_mask(
    mask: np.ndarray,
    *,
    close_kernel: int = 3,
    min_area: int = 200,
) -> np.ndarray:
    """Morphological close + largest-component selection."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_kernel, close_kernel))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    return _largest_component(closed, min_area=min_area)


# ----------------------------------------------------------- skeletonise

def skeleton_of(mask: np.ndarray) -> np.ndarray:
    """Return a binary 0/1 ndarray of the 1-pixel-wide skeleton."""
    binary = (mask > 0).astype(np.uint8)
    if not binary.any():
        return binary
    # skimage.skeletonize wants a bool ndarray; output is bool.
    skel = skeletonize(binary.astype(bool))
    return skel.astype(np.uint8)


# 8-connected neighbour offsets — we trace through diagonals because
# ``skeletonize`` produces 8-connected lines.
_NEIGHBORS_8 = (
    (-1, -1), (-1, 0), (-1, 1),
    ( 0, -1),          ( 0, 1),
    ( 1, -1), ( 1, 0), ( 1, 1),
)


def _neighbour_count(skel: np.ndarray, y: int, x: int) -> int:
    h, w = skel.shape
    n = 0
    for dy, dx in _NEIGHBORS_8:
        ny, nx = y + dy, x + dx
        if 0 <= ny < h and 0 <= nx < w and skel[ny, nx]:
            n += 1
    return n


def _find_endpoints(skel: np.ndarray) -> list[tuple[int, int]]:
    """Pixels with exactly one 8-connected neighbour. Path endpoints."""
    ys, xs = np.nonzero(skel)
    out: list[tuple[int, int]] = []
    for y, x in zip(ys.tolist(), xs.tolist()):
        if _neighbour_count(skel, y, x) == 1:
            out.append((y, x))
    return out


def _trace_from(
    skel: np.ndarray,
    start: tuple[int, int],
) -> list[tuple[int, int]]:
    """Walk the skeleton from ``start`` until no more unvisited neighbours.

    Tolerates branches by always preferring the lowest-degree continuation
    (an endpoint, then a 2-degree pixel) so we drift towards the far endpoint
    rather than a junction stub. Picks deterministically by neighbour offset
    order on ties.
    """
    h, w = skel.shape
    visited = np.zeros_like(skel, dtype=bool)
    path: list[tuple[int, int]] = []
    cur = start
    while cur is not None:
        y, x = cur
        if visited[y, x]:
            break
        visited[y, x] = True
        path.append((x, y))   # store as (x, y) for downstream geometry libs

        candidates: list[tuple[int, int, int]] = []
        for dy, dx in _NEIGHBORS_8:
            ny, nx = y + dy, x + dx
            if not (0 <= ny < h and 0 <= nx < w):
                continue
            if not skel[ny, nx] or visited[ny, nx]:
                continue
            candidates.append((_neighbour_count(skel, ny, nx), ny, nx))

        if not candidates:
            cur = None
        else:
            candidates.sort()  # lowest degree first; ties by (y, x)
            _, ny, nx = candidates[0]
            cur = (ny, nx)
    return path


def trace_route(
    skel: np.ndarray,
) -> list[tuple[int, int]]:
    """Order the skeleton pixels into a single polyline.

    Strategy:
      * If the skeleton has any endpoints (open path), seed from the first.
      * Otherwise treat as a closed loop: seed at the lowest (y, x) on-pixel.
      * Walk 8-connected neighbours, preferring the lowest-degree direction.

    Returns ``[(x, y), ...]`` in image coordinates (origin top-left).

    **Known limitation (kept for backwards compatibility):** at a junction
    (skeleton pixel with ≥3 neighbours) this function follows ONE branch
    and discards the others. Routes shaped like an animal (4 legs + head)
    have multiple junctions, so this often returns only ~30% of the
    skeleton. For full coverage, callers should use
    :func:`trace_all_polylines` instead.
    """
    if skel.dtype != np.uint8:
        skel = skel.astype(np.uint8)
    if not skel.any():
        return []

    endpoints = _find_endpoints(skel)
    if endpoints:
        # A clean open path has 2 endpoints. With branches we may have more —
        # walk from each endpoint and keep the longest path.
        best: list[tuple[int, int]] = []
        for start in endpoints:
            path = _trace_from(skel, start)
            if len(path) > len(best):
                best = path
        return best

    # Closed loop — pick the smallest-y, smallest-x pixel as a deterministic seed.
    ys, xs = np.nonzero(skel)
    idx = int(np.lexsort((xs, ys))[0])
    seed = (int(ys[idx]), int(xs[idx]))
    return _trace_from(skel, seed)


def _all_neighbours(skel: np.ndarray, y: int, x: int) -> list[tuple[int, int]]:
    """All 8-connected on-pixel neighbours of (y, x)."""
    h, w = skel.shape
    out: list[tuple[int, int]] = []
    for dy, dx in _NEIGHBORS_8:
        ny, nx = y + dy, x + dx
        if 0 <= ny < h and 0 <= nx < w and skel[ny, nx]:
            out.append((ny, nx))
    return out


def trace_all_polylines(
    skel: np.ndarray,
) -> list[list[tuple[int, int]]]:
    """Decompose the skeleton into ALL its simple-path edges.

    The skeleton of a branching shape is a planar graph: pixels with
    degree ≠ 2 are *nodes* (endpoints or junctions), pixels with degree 2
    are interior path pixels. Every edge of the graph goes node → node
    through some chain of degree-2 pixels. This function emits one
    polyline per edge.

    For a Y-shaped skeleton with junction J and tips T1, T2, T3 this
    returns three polylines: [T1..J], [J..T2], [J..T3] — every pixel
    covered, no pixel emitted twice (except junctions, which appear
    in every incident polyline so the polylines visually stitch).

    Empty input → empty list. A pure closed loop (no nodes) → one
    polyline traced via :func:`_trace_from` from a deterministic seed.

    Phase 4b: this fixes the dramatic loss documented in
    ``phase4b_diag/skeleton_diag_*.png`` where ``trace_route`` was
    only returning 25–67% of the skeleton's pixels on animal-shaped
    routes.
    """
    if skel.dtype != np.uint8:
        skel = skel.astype(np.uint8)
    if not skel.any():
        return []

    h, w = skel.shape

    # Pre-compute degree of every skeleton pixel
    degree = np.zeros_like(skel, dtype=np.int8)
    ys_arr, xs_arr = np.nonzero(skel)
    for y, x in zip(ys_arr.tolist(), xs_arr.tolist()):
        degree[y, x] = _neighbour_count(skel, y, x)

    is_node = (skel == 1) & (degree != 2)

    # No nodes → the skeleton is a single closed loop with no branches.
    # Fall back to the single-path tracer (which handles loops deterministically).
    if not is_node.any():
        return [trace_route(skel)]

    visited_non_node = np.zeros_like(skel, dtype=bool)
    polylines: list[list[tuple[int, int]]] = []

    node_ys, node_xs = np.nonzero(is_node)
    for y, x in zip(node_ys.tolist(), node_xs.tolist()):
        for ny, nx in _all_neighbours(skel, y, x):
            if is_node[ny, nx]:
                # node-to-node direct adjacency: emit once, in canonical order
                if (y, x) < (ny, nx):
                    polylines.append([(x, y), (nx, ny)])
                continue
            if visited_non_node[ny, nx]:
                continue
            # Walk along degree-2 pixels from (ny, nx) to the next node.
            polyline: list[tuple[int, int]] = [(x, y), (nx, ny)]
            visited_non_node[ny, nx] = True
            prev_y, prev_x = y, x
            cur_y, cur_x = ny, nx
            while True:
                next_nbr: tuple[int, int] | None = None
                for ay, ax in _all_neighbours(skel, cur_y, cur_x):
                    if (ay, ax) == (prev_y, prev_x):
                        continue
                    next_nbr = (ay, ax)
                    break
                if next_nbr is None:
                    break
                ay, ax = next_nbr
                polyline.append((ax, ay))
                if is_node[ay, ax]:
                    break
                if visited_non_node[ay, ax]:
                    break
                visited_non_node[ay, ax] = True
                prev_y, prev_x = cur_y, cur_x
                cur_y, cur_x = ay, ax
            polylines.append(polyline)

    # Sweep: any non-node skeleton pixels still unvisited belong to an
    # isolated closed loop that wasn't reachable from any node. Walk each
    # such loop deterministically.
    leftover = (skel == 1) & (~is_node) & (~visited_non_node)
    while leftover.any():
        ys_l, xs_l = np.nonzero(leftover)
        seed = (int(ys_l[0]), int(xs_l[0]))
        loop_polyline = _trace_from(skel, seed)
        if loop_polyline:
            polylines.append(loop_polyline)
            for x, y in loop_polyline:
                visited_non_node[y, x] = True
                leftover[y, x] = False
        else:
            break

    return polylines


# --------------------------------------------------------- public dataclass

@dataclass(frozen=True)
class RouteContour:
    """Outcome of contour extraction on one image.

    ``polyline`` is the legacy single-path trace (longest endpoint-to-endpoint
    path through the skeleton). It loses 30–70% of the skeleton on branching
    animal shapes — kept for backwards-compatibility with callers that
    expect a single ordered polyline (the affine fit's input is just
    *anchor* points so this is fine, but the city-scale fallback's input
    is the *shape* and should use ``polylines``).

    ``polylines`` is the full skeleton decomposed into simple-path edges —
    one polyline per node-to-node edge of the skeleton graph. Every
    skeleton pixel appears in at least one polyline. Use this when the
    full cartoon shape matters (city-scale projection, GPX rendering).
    """

    polyline: list[tuple[int, int]]              # legacy: single longest path
    polylines: list[list[tuple[int, int]]]       # full coverage (Phase 4b)
    mask: np.ndarray                             # binary uint8 (255/0) cleaned mask
    skeleton: np.ndarray                         # binary uint8 (1/0) skeleton

    @property
    def length_px(self) -> float:
        """Polyline length in pixels (Euclidean sum of segments, legacy path only)."""
        if len(self.polyline) < 2:
            return 0.0
        pts = np.asarray(self.polyline, dtype=float)
        return float(np.hypot(*np.diff(pts, axis=0).T).sum())

    @property
    def total_length_px(self) -> float:
        """Total length across ALL polylines — the true cartoon perimeter."""
        total = 0.0
        for p in self.polylines:
            if len(p) < 2:
                continue
            pts = np.asarray(p, dtype=float)
            total += float(np.hypot(*np.diff(pts, axis=0).T).sum())
        return total

    @property
    def skeleton_coverage(self) -> float:
        """Fraction of skeleton pixels covered by ``polylines`` (sanity check)."""
        skel_count = int(self.skeleton.sum()) if self.skeleton is not None else 0
        if skel_count == 0:
            return 0.0
        # Pixels may appear in multiple polylines (at junctions); dedupe.
        seen: set[tuple[int, int]] = set()
        for p in self.polylines:
            for px, py in p:
                seen.add((px, py))
        return len(seen) / float(skel_count)


def extract_route(
    bgr: np.ndarray,
    *,
    sat_min: int = 90,
    val_min: int = 60,
    close_kernel: int = 3,
    min_area: int = 200,
) -> RouteContour:
    """Run the full Phase 3 contour pipeline on a BGR image.

    See module docstring for stage details. Returns an empty polyline when
    the route mask is empty (e.g. a non-strav.art basemap-only image).

    Phase 4b: populates both ``polyline`` (legacy single longest path —
    used by the affine-fit's anchor list) AND ``polylines`` (full
    skeleton decomposed into all simple-path edges — used by the
    city-scale fallback and any caller that needs the complete cartoon).
    """
    raw = route_mask_colored(bgr, sat_min=sat_min, val_min=val_min)
    cleaned = clean_mask(raw, close_kernel=close_kernel, min_area=min_area)
    skel = skeleton_of(cleaned)
    polyline = trace_route(skel)
    polylines = trace_all_polylines(skel)
    return RouteContour(
        polyline=polyline,
        polylines=polylines,
        mask=cleaned,
        skeleton=skel,
    )
