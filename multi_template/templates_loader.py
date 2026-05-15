"""Load approved animal templates as normalized 2D point clouds.

Each template file is a dict with `points` list of [x, y] pairs from the
original quickdraw / stravart pipelines. We re-center, scale to unit bbox,
and resample to a target point count for downstream comparison.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

TEMPLATE_ROOT = Path(__file__).parent / "templates"


def _splice_loop(combined: np.ndarray, inner: np.ndarray) -> np.ndarray:
    """Splice an inner loop into a polyline at its closest-point pair.

    Finds (a, b) minimizing ||combined[a] - inner[b]||, then returns
    combined[:a+1] + inner_rotated_to_start_at_b_and_back_to_b + combined[a:].
    The double-listed bridge edge is the "go in, trace loop, come back" path —
    Dijkstra later re-routes it along available roads.
    """
    d2 = ((combined[:, None, :] - inner[None, :, :]) ** 2).sum(axis=2)
    flat = int(np.argmin(d2))
    a = flat // d2.shape[1]
    b = flat % d2.shape[1]
    rotated = np.concatenate([inner[b:], inner[:b], inner[b:b + 1]], axis=0)
    return np.concatenate([combined[:a + 1], rotated, combined[a:]], axis=0)


def _silhouette_outline(
    pts: np.ndarray,
    *,
    raster_size: int = 512,
    pad: float = 0.06,
    dilate_k: int = 3,
    close_k: int = 7,
    min_inner_area_frac: float = 0.005,
) -> np.ndarray:
    """Convert an unordered skeleton point cloud to a single ordered polyline
    that includes both the outer silhouette AND interior loops.

    Pipeline: rasterize → tiny dilate → morphological close → RETR_TREE contour
    hierarchy → splice each first-level child (interior hole) into the outer
    contour at its closest-point pair. Outer protrusions (trunk, ears, tail)
    are traced by the silhouette boundary; interior detail (gaps between legs,
    eye loops) is preserved by the spliced inner loops.

    RETR_EXTERNAL would flatten those inner loops into the outer envelope,
    losing the distinctive features that make the shape recognizable — see
    skill `gps-art-template-extraction` ("Never reduce a multi-loop route to
    its outer envelope"). Each spliced inner loop adds 5–15% perimeter.
    """
    if len(pts) < 4:
        return pts
    img = np.zeros((raster_size, raster_size), dtype=np.uint8)
    span = 1.0 + 2.0 * pad
    x = ((pts[:, 0] + 0.5 + pad) / span * (raster_size - 1)).astype(int)
    # Image y goes down; template y is "up positive" — flip.
    y = ((-pts[:, 1] + 0.5 + pad) / span * (raster_size - 1)).astype(int)
    x = np.clip(x, 0, raster_size - 1)
    y = np.clip(y, 0, raster_size - 1)
    img[y, x] = 255
    if dilate_k > 0:
        img = cv2.dilate(
            img, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_k, dilate_k))
        )
    closed = cv2.morphologyEx(
        img,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k)),
        iterations=2,
    )
    contours, hierarchy = cv2.findContours(
        closed, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE
    )
    if not contours or hierarchy is None:
        return pts
    h = hierarchy[0]  # each row: [next, prev, first_child, parent]

    # Pick the outermost (parent == -1) contour with the largest area.
    outer_idx, outer_area = -1, 0.0
    for i, ent in enumerate(h):
        if ent[3] == -1:
            a_i = cv2.contourArea(contours[i])
            if a_i > outer_area:
                outer_area, outer_idx = a_i, i
    if outer_idx < 0:
        return pts
    outer = contours[outer_idx].reshape(-1, 2).astype(float)

    # First-level interior holes (direct children) above an area threshold;
    # tiny holes are usually rasterization noise, not features.
    min_area = max(min_inner_area_frac * outer_area, 12.0)
    inner_loops = []
    ci = h[outer_idx][2]  # first child
    while ci != -1:
        if cv2.contourArea(contours[ci]) >= min_area:
            inner_loops.append(contours[ci].reshape(-1, 2).astype(float))
        ci = h[ci][0]  # next sibling

    # Splice inner loops in largest-first order so smaller features can attach
    # to whichever segment (outer OR previously spliced inner) is closest.
    inner_loops.sort(
        key=lambda c: -cv2.contourArea(c.astype(np.float32))
    )
    combined = outer
    for inner in inner_loops:
        combined = _splice_loop(combined, inner)

    # Raster pixel coords → normalized template coords [-0.5 .. 0.5].
    nx_pts = (combined[:, 0] / (raster_size - 1)) * span - 0.5 - pad
    ny_pts = -((combined[:, 1] / (raster_size - 1)) * span - 0.5 - pad)
    outline = np.column_stack([nx_pts, ny_pts])
    # Make the loop explicitly closed.
    if not np.allclose(outline[0], outline[-1]):
        outline = np.vstack([outline, outline[:1]])
    return outline


@dataclass
class Template:
    vote_id: str
    animal: str
    source_kind: str           # "quickdraw" or "stravart"
    points: np.ndarray         # (N, 2), centered on (0, 0), bbox max-side = 1.0
    path: Path

    @property
    def n_points(self) -> int:
        return self.points.shape[0]


def _normalize_points(raw: List[List[float]]) -> np.ndarray:
    pts = np.asarray(raw, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 4:
        raise ValueError("invalid points payload")
    # Both extractors (Quick Draw + strav.art) already store points with
    # Y-up convention (per gps-art-template-extraction skill: `ny = -(ys - cy)/s`
    # # flip Y: image coords are Y-down). Don't flip again — that would render
    # the elephant upside down on the map.
    pts = pts.copy()
    # Center on bbox center, scale so longest side = 1.0.
    mn = pts.min(axis=0)
    mx = pts.max(axis=0)
    center = (mn + mx) / 2.0
    extent = (mx - mn).max()
    if extent <= 0:
        raise ValueError("degenerate template")
    return (pts - center) / extent


def _resample_polyline(pts: np.ndarray, target: int) -> np.ndarray:
    """Arc-length resample a polyline to `target` evenly-spaced points."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return pts[:target]
    s = np.linspace(0.0, total, target)
    out_x = np.interp(s, cum, pts[:, 0])
    out_y = np.interp(s, cum, pts[:, 1])
    return np.column_stack([out_x, out_y])


def _smooth_outline(pts: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian-smooth a closed outline polyline along the arc.

    sigma is in outline-index units (e.g. sigma=2 on a 400-pt outline smooths
    features narrower than ~8 points while preserving features wider than ~20).
    Uses wrap-around boundary so the closure point isn't a discontinuity.
    Large sigma will swallow appendage tips — keep ≤ 3 for cosmetic smoothing.
    """
    from scipy.ndimage import gaussian_filter1d
    if sigma <= 0:
        return pts
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        body = pts[:-1]
        closed = True
    else:
        body = pts
        closed = False
    out_x = gaussian_filter1d(body[:, 0], sigma, mode="wrap")
    out_y = gaussian_filter1d(body[:, 1], sigma, mode="wrap")
    out = np.column_stack([out_x, out_y])
    if closed:
        out = np.vstack([out, out[:1]])
    return out


def load_template(path: Path, resample_n: int = 400, smooth_sigma: float = 0.0) -> Template:
    raw = json.loads(path.read_text())
    pts = _normalize_points(raw["points"])
    # The raw points are an unordered skeleton point cloud. Convert to an
    # ordered silhouette outline that preserves protrusions (trunk, legs, ears,
    # tail) — see _silhouette_outline above.
    pts = _silhouette_outline(pts)
    if resample_n and len(pts) != resample_n:
        pts = _resample_polyline(pts, resample_n)
    if smooth_sigma > 0:
        pts = _smooth_outline(pts, smooth_sigma)
    return Template(
        vote_id=raw["_vote_id"],
        animal=raw["_animal"],
        source_kind=raw["_source_kind"],
        points=pts,
        path=path,
    )


def load_animal_templates(
    animal: str,
    *,
    source_kind: Optional[str] = None,
    resample_n: int = 400,
    max_templates: Optional[int] = None,
    vote_ids: Optional[List[str]] = None,
    smooth_sigma: float = 0.0,
) -> List[Template]:
    """Load every approved template for an animal.

    `source_kind` filters to "quickdraw" or "stravart" if provided.
    `vote_ids`   restricts to exactly the listed IDs (e.g. ["ELE-Q01", "ELE-Q07"]);
                 takes precedence over `source_kind`.
    """
    adir = TEMPLATE_ROOT / animal
    if not adir.is_dir():
        raise FileNotFoundError(f"no templates dir for animal '{animal}'")
    files = sorted(adir.glob("*.json"))
    if vote_ids is not None:
        wanted = set(vote_ids)
        # Files are named e.g. QD_ELE-Q01.json or SA_ELE-S18.json
        files = [p for p in files if p.stem.split("_", 1)[1] in wanted]
    elif source_kind == "quickdraw":
        files = [p for p in files if p.name.startswith("QD_")]
    elif source_kind == "stravart":
        files = [p for p in files if p.name.startswith("SA_")]
    out = []
    for p in files:
        try:
            out.append(load_template(p, resample_n=resample_n, smooth_sigma=smooth_sigma))
        except (ValueError, KeyError) as e:
            print(f"  skip {p.name}: {e}")
    if max_templates is not None:
        out = out[:max_templates]
    return out


def template_summary() -> dict:
    p = TEMPLATE_ROOT / "_summary.json"
    return json.loads(p.read_text())


if __name__ == "__main__":
    summ = template_summary()
    print("Approved-template inventory:")
    for animal, counts in summ.items():
        print(f"  {animal:10s} qd={counts['quickdraw']:3d}  sa={counts['stravart']:3d}  total={counts['total']:3d}")
    eles = load_animal_templates("elephant")
    print(f"\nLoaded {len(eles)} elephant templates; first: {eles[0].vote_id} pts={eles[0].n_points} bbox={eles[0].points.min(0)}..{eles[0].points.max(0)}")
