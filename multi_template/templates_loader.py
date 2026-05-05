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

import numpy as np
from shapely import concave_hull
from shapely.geometry import MultiPoint

TEMPLATE_ROOT = Path(__file__).parent / "templates"


def _outline_from_pointcloud(pts: np.ndarray, ratio: float = 0.18) -> np.ndarray:
    """The raw `points` are unordered skeleton pixels. Compute a concave
    hull outline so we have a sensible single closed traversal for routing.

    `ratio` controls "tightness": 0 → convex hull, 1 → very tight to points.
    0.15-0.25 gives a nice silhouette for blob-like animals.
    """
    if len(pts) < 4:
        return pts
    mp = MultiPoint([tuple(p) for p in pts])
    poly = concave_hull(mp, ratio=ratio)
    if poly is None or poly.is_empty:
        return pts
    if poly.geom_type == "Polygon":
        coords = np.asarray(poly.exterior.coords)
    elif poly.geom_type == "MultiPolygon":
        # Pick the largest piece
        best = max(poly.geoms, key=lambda g: g.area)
        coords = np.asarray(best.exterior.coords)
    else:
        return pts
    return coords


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
    # Templates from quickdraw use (x, y) where +y is "down" in image coords.
    # Flip y so visual up == positive y for routing/preview consistency.
    pts = pts.copy()
    pts[:, 1] = -pts[:, 1]
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


def load_template(path: Path, resample_n: int = 200, hull_ratio: float = 0.18) -> Template:
    raw = json.loads(path.read_text())
    pts = _normalize_points(raw["points"])
    # The raw points are unordered skeleton pixels. Replace with the concave
    # hull boundary — that's an actual silhouette outline we can route.
    pts = _outline_from_pointcloud(pts, ratio=hull_ratio)
    if resample_n and len(pts) != resample_n:
        pts = _resample_polyline(pts, resample_n)
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
    resample_n: int = 200,
    max_templates: Optional[int] = None,
) -> List[Template]:
    """Load every approved template for an animal.

    `source_kind` filters to "quickdraw" or "stravart" if provided.
    """
    adir = TEMPLATE_ROOT / animal
    if not adir.is_dir():
        raise FileNotFoundError(f"no templates dir for animal '{animal}'")
    files = sorted(adir.glob("*.json"))
    if source_kind == "quickdraw":
        files = [p for p in files if p.name.startswith("QD_")]
    elif source_kind == "stravart":
        files = [p for p in files if p.name.startswith("SA_")]
    out = []
    for p in files:
        try:
            out.append(load_template(p, resample_n=resample_n))
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
