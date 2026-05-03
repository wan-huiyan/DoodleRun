"""Vision-extract shape templates from strav.art gallery images.

Each image is a screenshot of a finished Strava activity: a red polyline drawn
over a Google/Apple/OSM map background. We don't care about the map; we want the
SHAPE of the red trace, normalized to abstract [-0.5, 0.5]^2 coordinates.

Pipeline:
  1. Decode image, convert BGR->HSV.
  2. HSV-mask "red" (H near 0 OR near 180, S high, V mid-high).
  3. Morphological close with a small kernel — heals 1-3 px gaps in the line.
  4. Optional small dilation to thicken before contour finding.
  5. cv2.findContours, RETR_EXTERNAL — outermost boundary of all red blobs.
  6. Take the contour with the largest area; reject if < 1% of image area
     (probably a stray label or pin, not the route).
  7. cv2.approxPolyDP at epsilon = 0.001 * arcLength to drop near-collinear pts.
  8. Convert to (x, y) list, flip Y (image coords -> math coords), normalize to
     [-0.5, 0.5]^2 preserving aspect.
  9. Visvalingam-Whyatt simplify to ~40 points (binary search on epsilon).

Reject:
- contour area / image area < 0.01  (likely noise, not the route)
- vertex count after step 9 < 12  (too crude)
- bbox aspect ratio outside [0.4, 4.0]  (probably a long word/letter, not animal)
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
from shapely.geometry import Polygon

try:
    from simplification.cutil import simplify_coords_vw
except Exception:
    simplify_coords_vw = None


CATEGORIES = ["pig", "cat", "dog", "dragon", "duck", "elephant"]
TARGET_POINTS = 40


@dataclass
class StravResult:
    source: str
    coords: list[tuple[float, float]]
    bbox_aspect: float
    n_points: int
    area_frac: float
    score: float
    reason: str = "ok"


def red_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # Two ranges because red wraps around 0/180 in OpenCV's H scale (0..179).
    m1 = cv2.inRange(hsv, (0,   90, 60),  (12,  255, 255))
    m2 = cv2.inRange(hsv, (160, 90, 60),  (179, 255, 255))
    return cv2.bitwise_or(m1, m2)


def vw_to_target(coords, target, max_iters=30):
    if simplify_coords_vw is None or len(coords) <= target:
        return coords
    xs = [p[0] for p in coords]; ys = [p[1] for p in coords]
    bbox_area = (max(xs)-min(xs)) * (max(ys)-min(ys)) or 1.0
    lo, hi = 0.0, bbox_area
    best = list(coords)
    for _ in range(max_iters):
        mid = (lo + hi) / 2
        if mid == 0:
            break
        simp = simplify_coords_vw(coords, mid)
        n = len(simp)
        if abs(n - target) < abs(len(best) - target):
            best = [tuple(p) for p in simp]
        if n == target:
            return best
        if n > target:
            lo = mid
        else:
            hi = mid
    return best


def extract_one(img_path: Path) -> Optional[StravResult]:
    bgr = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    if bgr is None:
        return StravResult(img_path.name, [], 0, 0, 0, -1, "decode_failed")
    H, W = bgr.shape[:2]
    if H * W < 50_000:
        return StravResult(img_path.name, [], 0, 0, 0, -1, "too_small")

    mask = red_mask(bgr)
    # Close small gaps and thicken.
    k = max(3, int(min(H, W) / 200) | 1)   # odd, scales with image
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.dilate(mask, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return StravResult(img_path.name, [], 0, 0, 0, -1, "no_contours")
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    cnt = contours[0]
    area = float(cv2.contourArea(cnt))
    img_area = float(H * W)
    area_frac = area / img_area
    if area_frac < 0.01:
        return StravResult(img_path.name, [], 0, 0, area_frac, -1, "contour_too_small")

    # Approx with light tolerance; arcLength*0.001 ≈ 0.1% of perimeter.
    peri = cv2.arcLength(cnt, True)
    approx = cv2.approxPolyDP(cnt, 0.001 * peri, True)
    pts = [(float(p[0][0]), float(p[0][1])) for p in approx]

    # Y flip + normalize to [-0.5, 0.5]^2.
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
    w, h = max(xs)-min(xs), max(ys)-min(ys)
    s = max(w, h)
    if s <= 0:
        return StravResult(img_path.name, [], 0, 0, area_frac, -1, "degenerate_bbox")
    norm = [((p[0]-cx)/s, -(p[1]-cy)/s) for p in pts]
    aspect = w / h if h > 0 else 0.0
    if not (0.4 <= aspect <= 4.0):
        return StravResult(img_path.name, [], 0, 0, area_frac, -1, "bad_aspect")

    if norm[0] != norm[-1]:
        norm.append(norm[0])

    simp = vw_to_target(norm, target=TARGET_POINTS)
    if simp[0] != simp[-1]:
        simp = simp + [simp[0]]
    n_eff = len(simp) - 1
    if n_eff < 12:
        return StravResult(img_path.name, [], aspect, n_eff, area_frac, -1, "too_few_points")

    # Score:
    #  - large area_frac (route fills the image well) is good
    #  - aspect close to 1.4 (typical animal silhouette) is good
    #  - moderate vertex count near target is good
    log_asp = math.log(max(0.001, aspect))
    aspect_pen = abs(log_asp - math.log(1.4))
    vert_pen = abs(n_eff - TARGET_POINTS) / TARGET_POINTS
    area_score = min(1.0, area_frac * 4.0)   # peaks at 25% coverage
    score = (
        + 1.5 * area_score
        - 0.7 * aspect_pen
        - 0.3 * vert_pen
    )

    return StravResult(
        source=img_path.name,
        coords=[(round(x, 5), round(y, 5)) for x, y in simp],
        bbox_aspect=float(aspect),
        n_points=n_eff,
        area_frac=area_frac,
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
        kept: list[StravResult] = []
        reasons: dict[str, int] = {}
        files = sorted(in_dir.glob("*.jpg")) + sorted(in_dir.glob("*.png"))
        for p in files:
            r = extract_one(p)
            if r is None or r.reason != "ok":
                reasons[r.reason if r else "none"] = reasons.get(r.reason if r else "none", 0) + 1
                continue
            kept.append(r)
        kept.sort(key=lambda r: -r.score)
        for rank, r in enumerate(kept):
            payload = {
                "rank": rank,
                "source": r.source,
                "category": cat,
                "n_points": r.n_points,
                "bbox_aspect": r.bbox_aspect,
                "area_frac": r.area_frac,
                "score": r.score,
                "coords": [list(p) for p in r.coords],
            }
            (cat_dir / f"{rank:03d}_{r.source}.json").write_text(json.dumps(payload))
        summary[cat] = {
            "input_files": len(files),
            "kept": len(kept),
            "reject_reasons": reasons,
        }
        print(f"[{cat}] in={len(files)} kept={len(kept)} rejects={reasons}")
    (out_root / "extract_summary.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
