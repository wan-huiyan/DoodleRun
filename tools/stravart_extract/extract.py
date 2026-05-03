"""Extract template polylines from strav.art gallery images.

Pipeline per image:
  1. Load (cv2.imread handles JPEG/PNG/WebP via stb_image).
  2. HSV threshold for red/orange route line, dilate-close small gaps.
  3. Find external contours, pick the largest by area.
  4. Reject if contour is a degenerate strip (low compactness) or fills
     too little / too much of the frame.
  5. Visvalingam-Whyatt simplify the closed contour to ~TARGET_POINTS.
  6. Normalize the bounding box to [0,1] x [0,1] with origin top-left
     flipped to bottom-left (cartesian, matches existing shapes.py).
  7. Write per-image JSON {category, source_image, points, n_anchors,
     bbox_aspect, fill_ratio, source_url} into out/<category>/.

The output coordinates are *abstract* — we keep only the silhouette in
its own normalized frame and discard all map / geographic context.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from simplification.cutil import simplify_coords_vw_idx

# Red/orange spans both ends of the hue circle. The strav.art trace
# samples I inspected fall in roughly H ∈ {0..15, 165..180}, S ≥ 90, V ≥ 90.
HSV_RED_LOW1 = np.array([0, 90, 90])
HSV_RED_HIGH1 = np.array([15, 255, 255])
HSV_RED_LOW2 = np.array([165, 90, 90])
HSV_RED_HIGH2 = np.array([180, 255, 255])

# Quality-filter thresholds. These are intentionally permissive on this
# pass — the user reviews preview grids and we re-filter from votes.
MIN_FILL_FRAC = 0.005    # contour bbox area / frame area
MAX_FILL_FRAC = 0.85
MIN_ASPECT = 0.25        # bbox aspect ratio — reject super-skinny detections
MAX_ASPECT = 4.0
MIN_PERIMETER_PX = 200
TARGET_POINTS = 30
MIN_KEPT_POINTS = 12
MAX_KEPT_POINTS = 60
# Reject images where the largest red blob is < this fraction of the total
# red mask area — those are fragmented (e.g. multi-piece map labels) and
# we'd only capture one slice of the artwork.
MIN_DOMINANCE = 0.55


@dataclass
class Template:
    category: str
    source_image: str
    source_url: Optional[str]
    points: list[list[float]]   # closed polygon in [0,1]^2 (cartesian, y-up)
    n_anchors: int
    bbox_aspect: float          # width / height of normalized bbox in pixel space
    fill_ratio: float           # contour_area / frame_area
    contour_solidity: float     # area / convex_hull_area  (1 = convex blob)
    dominance: float            # largest_contour_pixels / total_red_pixels


def red_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, HSV_RED_LOW1, HSV_RED_HIGH1)
    m2 = cv2.inRange(hsv, HSV_RED_LOW2, HSV_RED_HIGH2)
    mask = cv2.bitwise_or(m1, m2)
    # Close small gaps along the trace (anti-aliased pixels and tile seams).
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    return mask


def largest_external_contour(mask: np.ndarray) -> Optional[np.ndarray]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def simplify_to_target(points: np.ndarray, target: int = TARGET_POINTS) -> np.ndarray:
    """VW-simplify a closed polyline to ~target vertices.

    `simplify_coords_vw_idx` returns indices of the kept points sorted by
    "effective area" (largest first). We binary-search the threshold by
    just slicing the index list, but VW gives us indices over a tolerance,
    not a count — so we sweep tolerance until we land near target.
    """
    if len(points) <= target:
        return points
    # Sweep tolerances log-spaced; pick the one whose kept count is
    # closest to target while ≥ MIN_KEPT_POINTS.
    pts_list = points.tolist()
    best_kept = None
    for tol in np.geomspace(0.01, 1000.0, num=24):
        kept_idx = simplify_coords_vw_idx(pts_list, float(tol))
        n = len(kept_idx)
        if n < MIN_KEPT_POINTS:
            break
        if best_kept is None or abs(n - target) < abs(len(best_kept) - target):
            best_kept = kept_idx
        if n <= target:
            break
    if best_kept is None:
        return points
    return points[np.array(best_kept)]


def extract_template(img_path: Path, category: str, source_url: Optional[str]) -> Optional[Template]:
    bgr = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    h, w = bgr.shape[:2]
    frame_area = float(h * w)
    mask = red_mask(bgr)
    total_red = float(int(mask.sum()) // 255) or 1.0
    contour = largest_external_contour(mask)
    if contour is None or len(contour) < 20:
        return None
    contour_pts = contour[:, 0, :].astype(np.float32)  # (N, 2) in (x, y) pixel coords

    area = float(cv2.contourArea(contour))
    perim = float(cv2.arcLength(contour, True))
    if perim < MIN_PERIMETER_PX:
        return None
    # Pixel coverage of largest contour vs total red — rejects fragmented
    # multi-piece images where we'd only recover one slice.
    contour_mask = np.zeros_like(mask)
    cv2.drawContours(contour_mask, [contour], -1, color=255, thickness=cv2.FILLED)
    covered = float(int(cv2.bitwise_and(mask, contour_mask).sum()) // 255) or 1.0
    dominance = covered / total_red
    if dominance < MIN_DOMINANCE:
        return None

    x, y, bw, bh = cv2.boundingRect(contour)
    fill_ratio = (bw * bh) / frame_area
    if fill_ratio < MIN_FILL_FRAC or fill_ratio > MAX_FILL_FRAC:
        return None
    aspect = bw / max(bh, 1)
    if aspect < MIN_ASPECT or aspect > MAX_ASPECT:
        return None

    hull = cv2.convexHull(contour)
    hull_area = float(cv2.contourArea(hull))
    solidity = (area / hull_area) if hull_area > 0 else 0.0

    simplified = simplify_to_target(contour_pts, TARGET_POINTS)
    if len(simplified) < MIN_KEPT_POINTS or len(simplified) > MAX_KEPT_POINTS:
        return None

    # Normalize: shift to bbox origin, scale so the longer side = 1.0,
    # center the shorter side, flip y so up = +y (matches shapes.py).
    xs, ys = simplified[:, 0], simplified[:, 1]
    minx, miny = float(xs.min()), float(ys.min())
    maxx, maxy = float(xs.max()), float(ys.max())
    span_x = max(maxx - minx, 1.0)
    span_y = max(maxy - miny, 1.0)
    span = max(span_x, span_y)
    pad_x = (span - span_x) / 2.0
    pad_y = (span - span_y) / 2.0
    nx = (xs - minx + pad_x) / span
    ny_top = (ys - miny + pad_y) / span
    ny = 1.0 - ny_top  # flip to cartesian

    points = [[float(a), float(b)] for a, b in zip(nx, ny)]
    # Ensure closed (first == last).
    if points[0] != points[-1]:
        points.append(points[0])

    return Template(
        category=category,
        source_image=img_path.name,
        source_url=source_url,
        points=points,
        n_anchors=len(points) - 1,
        bbox_aspect=float(aspect),
        fill_ratio=float(fill_ratio),
        contour_solidity=float(solidity),
        dominance=float(dominance),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=Path, default=Path("scratch/stravart_images"))
    ap.add_argument("--out", type=Path, default=Path("templates_stravart"))
    ap.add_argument("--category", action="append", help="Limit to category subdirs")
    args = ap.parse_args()

    manifest_path = args.images / "manifest.json"
    url_lookup: dict[str, str] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for cat, items in manifest.items():
            for item in items:
                url_lookup[f"{cat}/{item['filename']}"] = item["url"]

    cats = args.category or sorted(p.name for p in args.images.iterdir() if p.is_dir())
    args.out.mkdir(parents=True, exist_ok=True)

    summary: dict[str, dict] = {}
    for cat in cats:
        cat_dir = args.images / cat
        if not cat_dir.is_dir():
            continue
        out_dir = args.out / cat
        out_dir.mkdir(parents=True, exist_ok=True)
        kept = 0
        skipped = 0
        for img_path in sorted(cat_dir.iterdir()):
            if not img_path.is_file():
                continue
            try:
                src_url = url_lookup.get(f"{cat}/{img_path.name}")
                tpl = extract_template(img_path, cat, src_url)
            except Exception as exc:
                print(f"[{cat}/{img_path.name}] extract error: {exc}", file=sys.stderr)
                skipped += 1
                continue
            if tpl is None:
                skipped += 1
                continue
            json_path = out_dir / (img_path.stem + ".json")
            json_path.write_text(json.dumps(asdict(tpl), indent=2))
            kept += 1
        total = kept + skipped
        summary[cat] = {"kept": kept, "skipped": skipped, "total": total}
        print(f"[{cat}] kept {kept}/{total} ({skipped} rejected)")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
