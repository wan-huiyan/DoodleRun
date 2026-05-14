"""Extract route SHAPE templates from strav.art gallery images via skeletonization.

OLD APPROACH (broken): HSV red mask + morphological close + dilate +
RETR_EXTERNAL contour. The OUTER envelope of a multi-loop route line LOSES the
interior loops — for an elephant, all four leg-down-loops vanish and you
recover only the body silhouette.

NEW APPROACH: HSV mask the route line (red + magenta + deep pink, wider than
before) -> tiny morphological close to bridge sub-line gaps -> skimage
skeletonize -> 1-pixel-wide line that preserves every leg loop, ear, trunk,
tail. Output the skeleton as a normalized point cloud (no ordering required —
downstream scoring uses Modified Hausdorff / Chamfer between point clouds,
order-invariant).

For visualization the points are plotted as small dots; at typical skeleton
point counts (1k-8k pixels per image) the dots visually merge into the route
line at preview-grid resolution.

We also keep the largest-connected-component filter softly: include extra
components only if they're at least 5% of the largest component's pixel count
(filters out noise, but keeps disconnected appendages when the original
route line had small visual gaps).
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from skimage.morphology import skeletonize


CATEGORIES = ["pig", "cat", "dog", "dragon", "duck", "elephant"]
MAX_POINTS = 4000          # cap per template to keep JSON small (~80KB)
MIN_POINTS = 80            # below this -> reject
MIN_COMPONENT_FRAC = 0.05  # keep components >= 5% of largest


@dataclass
class StravResult:
    source: str
    points: list[tuple[float, float]]   # normalized point cloud
    bbox_aspect: float
    n_points: int
    n_components_kept: int
    image_coverage: float                # mask px / image px
    score: float
    reason: str = "ok"


def wide_route_mask(bgr: np.ndarray) -> np.ndarray:
    """HSV mask covering: red, deep pink, magenta, dark red, salmon."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, (0,   60, 50),  (15,  255, 255))
    m2 = cv2.inRange(hsv, (155, 60, 50),  (179, 255, 255))
    m3 = cv2.inRange(hsv, (140, 80, 50),  (170, 255, 255))
    return cv2.bitwise_or(cv2.bitwise_or(m1, m2), m3)


def extract_one(img_path: Path) -> Optional[StravResult]:
    bgr = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    if bgr is None:
        return StravResult(img_path.name, [], 0, 0, 0, 0, -1, "decode_failed")
    H, W = bgr.shape[:2]
    if H * W < 50_000:
        return StravResult(img_path.name, [], 0, 0, 0, 0, -1, "too_small")

    mask = wide_route_mask(bgr)
    coverage = float(np.count_nonzero(mask)) / float(H * W)
    if coverage < 0.002:
        return StravResult(img_path.name, [], 0, 0, 0, coverage, -1, "no_route_pixels")

    # Tiny close to bridge sub-pixel gaps WITHOUT thickening enough to merge
    # adjacent loops.
    k = max(3, int(min(H, W) / 300) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    # Skeletonize — gives a 1-px-wide line preserving all leg loops.
    skel = skeletonize(closed > 0).astype(np.uint8)
    if skel.sum() < MIN_POINTS:
        return StravResult(img_path.name, [], 0, 0, 0, coverage, -1, "skeleton_too_short")

    # Keep the dominant connected components.
    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(skel)
    if n_lab <= 1:
        return StravResult(img_path.name, [], 0, 0, 0, coverage, -1, "no_components")
    sizes = [(lab, stats[lab, cv2.CC_STAT_AREA]) for lab in range(1, n_lab)]
    sizes.sort(key=lambda kv: -kv[1])
    largest = sizes[0][1]
    keep_labels = {lab for lab, sz in sizes if sz >= MIN_COMPONENT_FRAC * largest}
    keep_mask = np.isin(labels, list(keep_labels))
    ys, xs = np.where(keep_mask)
    if len(xs) < MIN_POINTS:
        return StravResult(img_path.name, [], 0, 0, 0, coverage, -1, "too_few_skel_points")

    # Subsample if very dense.
    if len(xs) > MAX_POINTS:
        idx = np.random.default_rng(seed=hash(img_path.name) & 0xFFFF).choice(
            len(xs), MAX_POINTS, replace=False
        )
        xs, ys = xs[idx], ys[idx]

    # Normalize to [-0.5, 0.5]^2 with Y flipped so positive Y is up.
    xs = xs.astype(float)
    ys = ys.astype(float)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    w, h = xs.max() - xs.min(), ys.max() - ys.min()
    s = max(w, h)
    if s <= 0:
        return StravResult(img_path.name, [], 0, 0, 0, coverage, -1, "degenerate_bbox")
    nx = (xs - cx) / s
    ny = -(ys - cy) / s
    aspect = float(w / h) if h > 0 else 0.0
    if not (0.4 <= aspect <= 4.0):
        return StravResult(img_path.name, [], aspect, len(nx), len(keep_labels), coverage, -1, "bad_aspect")

    points = list(zip(nx.tolist(), ny.tolist()))

    # Score:
    # - more skeleton coverage (relative to image) is good — full body+legs visible
    # - aspect close to 1.4 (typical animal silhouette)
    # - prefer 1-3 connected components (well-connected route line). MANY
    #   components suggests a fragmented red line (poor source image)
    log_asp = math.log(max(0.001, aspect))
    aspect_pen = abs(log_asp - math.log(1.4))
    coverage_score = min(1.0, coverage * 60.0)   # peaks at 1.7% coverage
    n_comp = len(keep_labels)
    comp_pen = 0.15 * max(0, n_comp - 3)
    score = (
        + 1.5 * coverage_score
        - 0.7 * aspect_pen
        - comp_pen
    )

    return StravResult(
        source=img_path.name,
        points=[(round(x, 5), round(y, 5)) for x, y in points],
        bbox_aspect=aspect,
        n_points=len(points),
        n_components_kept=n_comp,
        image_coverage=coverage,
        score=float(score),
        reason="ok",
    )


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    raw_dir = root / "data" / "strav_raw"
    out_root = root / "templates_strav"
    summary = {}
    for cat in CATEGORIES:
        in_dir = raw_dir / cat
        if not in_dir.exists():
            print(f"[{cat}] missing raw dir")
            continue
        cat_dir = out_root / cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        for old in cat_dir.glob("*.json"):
            old.unlink()
        kept = []
        reasons: dict[str, int] = {}
        files = sorted(in_dir.glob("*.jpg")) + sorted(in_dir.glob("*.png"))
        for p in files:
            r = extract_one(p)
            if r is None or r.reason != "ok":
                key = r.reason if r else "none"
                reasons[key] = reasons.get(key, 0) + 1
                continue
            kept.append(r)
        kept.sort(key=lambda r: -r.score)
        for rank, r in enumerate(kept):
            payload = {
                "rank": rank,
                "source": r.source,
                "category": cat,
                "format": "skeleton_pointcloud",
                "n_points": r.n_points,
                "n_components_kept": r.n_components_kept,
                "bbox_aspect": r.bbox_aspect,
                "image_coverage": r.image_coverage,
                "score": r.score,
                "points": [list(p) for p in r.points],
            }
            (cat_dir / f"{rank:03d}_{r.source}.json").write_text(json.dumps(payload))
        summary[cat] = {"input": len(files), "kept": len(kept), "reject_reasons": reasons}
        print(f"[{cat}] in={len(files)} kept={len(kept)} rejects={reasons}")
    (out_root / "extract_summary.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
