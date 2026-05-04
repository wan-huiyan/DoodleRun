"""Extract Quick Draw sketches as skeleton point clouds.

OLD APPROACH (broken): Pick longest stroke as the "main outline", filter
non-main strokes by buffered-convex-hull membership (>=70% inside -> drop as
interior detail; otherwise splice as out-and-back spike). For elephants and
other quadrupeds this lost legs (often >70% inside the body's convex hull)
and produced tangled chaos when the user drew the body as two strokes
(front+back) — only one would be the "main outline" and the other became
an out-and-back spike crossing through the middle.

NEW APPROACH (mirrors the strav.art skeletonize fix): rasterize EVERY stroke
the user drew onto a binary canvas with a thickness wide enough to bridge
sub-pixel gaps, optionally morphological-close to merge near-touching
strokes, skeletonize to a 1-px-wide line that preserves every leg loop, ear,
trunk, tail, then emit the skeleton as a normalized point cloud.

This matches the strav.art template format (`format: skeleton_pointcloud`),
so downstream scoring (Modified Hausdorff / Chamfer between point clouds —
order-invariant) works the same way for both sources.

Why this is the right call for GPS-art: real runners trace EVERYTHING the
artist drew, not the convex envelope. A stroke-based dataset like Quick Draw
already tells us what the artist drew. Rasterizing all strokes preserves
that intent; skeletonizing converts the thick rendering back to a single-px
trace suitable for matching against road-network polylines.

Output: sketches/{category}/<rank>_<key_id>.json   (skeleton_pointcloud format)
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

# Quick Draw native canvas is 256x256. We render at that resolution.
CANVAS_PX = 256
# Stroke thickness for rasterization. Quick Draw raw strokes are 1-px polylines
# with minor jitter. 3px is enough to bridge sub-pixel gaps within a stroke
# without merging adjacent legs.
STROKE_PX = 3
# Morphological close radius (px). Just enough to bridge tiny gaps between
# stroke endpoints (e.g. a leg whose top doesn't quite touch the body).
# Keep tight so adjacent legs don't merge into a single bar.
CLOSE_PX = 1

# Output sizing.
MAX_POINTS = 4000           # cap per template (matches strav.art)
MIN_POINTS = 60             # below this -> reject
MIN_COMPONENT_FRAC = 0.05   # keep components >= 5% of largest
MAX_STROKES = 12            # higher than v1 (was 8); detailed elephants use 9-11
TARGET_KEEP = 200           # top-N by score per category


@dataclass
class Result:
    key_id: str
    category: str
    points: list[tuple[float, float]]
    bbox_aspect: float
    n_points: int
    n_strokes: int
    n_components_kept: int
    skeleton_px: int
    score: float
    reason: str = "ok"
    n_endpoints: int = 0


def rasterize_strokes(strokes, canvas_px=CANVAS_PX, thickness=STROKE_PX) -> np.ndarray:
    """Render strokes onto a binary canvas, sized to the strokes' bbox padded
    so the silhouette nearly fills the canvas. Returns uint8 0/255 mask."""
    all_x = [x for s in strokes for x in s[0]]
    all_y = [y for s in strokes for y in s[1]]
    if not all_x or not all_y:
        return np.zeros((canvas_px, canvas_px), dtype=np.uint8)
    minx, maxx = min(all_x), max(all_x)
    miny, maxy = min(all_y), max(all_y)
    w, h = max(1, maxx - minx), max(1, maxy - miny)
    # Fit into 92% of canvas, centered. Preserve aspect.
    pad = canvas_px * 0.04
    avail = canvas_px - 2 * pad
    s = avail / max(w, h)
    ox = pad + (avail - w * s) / 2 - minx * s
    oy = pad + (avail - h * s) / 2 - miny * s
    canvas = np.zeros((canvas_px, canvas_px), dtype=np.uint8)
    for stroke in strokes:
        xs, ys = stroke[0], stroke[1]
        if len(xs) < 2:
            continue
        pts = np.column_stack([
            (np.asarray(xs, dtype=float) * s + ox).round().astype(np.int32),
            (np.asarray(ys, dtype=float) * s + oy).round().astype(np.int32),
        ])
        cv2.polylines(canvas, [pts], isClosed=False, color=255,
                      thickness=thickness, lineType=cv2.LINE_8)
    return canvas


def extract(rec: dict) -> Result:
    key_id = str(rec.get("key_id", "?"))
    drawing = rec.get("drawing")
    word = rec.get("word", "?")
    if not drawing:
        return Result(key_id, word, [], 0, 0, 0, 0, 0, -1, "empty")
    if len(drawing) > MAX_STROKES:
        return Result(key_id, word, [], 0, 0, len(drawing), 0, 0, -1, "too_many_strokes")

    # Strokes are [[xs], [ys]] or [[xs], [ys], [ts]]; we only need xs/ys.
    strokes = []
    for s in drawing:
        if len(s) < 2:
            continue
        xs, ys = s[0], s[1]
        if len(xs) < 2 or len(ys) < 2 or len(xs) != len(ys):
            continue
        strokes.append((list(xs), list(ys)))
    if not strokes:
        return Result(key_id, word, [], 0, 0, 0, 0, 0, -1, "no_strokes")

    # Rasterize all strokes thick.
    canvas = rasterize_strokes(strokes)
    if canvas.sum() == 0:
        return Result(key_id, word, [], 0, 0, len(strokes), 0, 0, -1, "blank_canvas")

    # Tiny morph close to bridge tiny gaps where stroke endpoints almost touch.
    if CLOSE_PX > 0:
        k = max(3, 2 * CLOSE_PX + 1) | 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        canvas = cv2.morphologyEx(canvas, cv2.MORPH_CLOSE, kernel, iterations=1)

    # Skeletonize.
    skel = skeletonize(canvas > 0).astype(np.uint8)
    skel_px = int(skel.sum())
    if skel_px < MIN_POINTS:
        return Result(key_id, word, [], 0, 0, len(strokes), 0, skel_px, -1, "skeleton_too_short")

    # Endpoints = skeleton pixels with exactly 1 skeleton neighbor.
    # Many endpoints => prongs (legs, trunk, tail tips) => anatomical detail.
    # Zero endpoints => closed-loop silhouette (oval blob with no protrusions).
    # Convolving with a 3x3 ones kernel counts self+neighbors; subtract self
    # then mask to skeleton pixels.
    nbr_kernel = np.ones((3, 3), dtype=np.uint8)
    nbr_count = cv2.filter2D(skel, -1, nbr_kernel, borderType=cv2.BORDER_CONSTANT) - skel
    n_endpoints = int(((skel == 1) & (nbr_count == 1)).sum())

    # Keep dominant connected components.
    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(skel)
    if n_lab <= 1:
        return Result(key_id, word, [], 0, 0, len(strokes), 0, skel_px, -1, "no_components")
    sizes = [(lab, stats[lab, cv2.CC_STAT_AREA]) for lab in range(1, n_lab)]
    sizes.sort(key=lambda kv: -kv[1])
    largest = sizes[0][1]
    keep_labels = {lab for lab, sz in sizes if sz >= MIN_COMPONENT_FRAC * largest}
    keep_mask = np.isin(labels, list(keep_labels))
    ys, xs = np.where(keep_mask)
    if len(xs) < MIN_POINTS:
        return Result(key_id, word, [], 0, 0, len(strokes), len(keep_labels), skel_px,
                      -1, "too_few_skel_points")

    # Subsample if very dense.
    if len(xs) > MAX_POINTS:
        rng = np.random.default_rng(seed=int(key_id) & 0xFFFF)
        idx = rng.choice(len(xs), MAX_POINTS, replace=False)
        xs, ys = xs[idx], ys[idx]

    # Normalize to [-0.5, 0.5]^2 with Y up (Quick Draw is screen-coords Y-down).
    xs = xs.astype(float)
    ys = ys.astype(float)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    w, h = xs.max() - xs.min(), ys.max() - ys.min()
    s_norm = max(w, h)
    if s_norm <= 0:
        return Result(key_id, word, [], 0, 0, len(strokes), len(keep_labels), skel_px,
                      -1, "degenerate_bbox")
    nx = (xs - cx) / s_norm
    ny = -(ys - cy) / s_norm   # flip Y for "up is positive"
    aspect = float(w / h) if h > 0 else 0.0
    if not (0.4 <= aspect <= 4.0):
        return Result(key_id, word, [], aspect, len(nx), len(strokes), len(keep_labels),
                      skel_px, -1, "bad_aspect")

    points = list(zip(nx.tolist(), ny.tolist()))

    # Score:
    # - prefer aspect ratio near 1.4 (typical quadruped silhouette)
    # - prefer 1-3 connected components (well-connected drawing). Many components
    #   means the artist drew lots of disconnected detail (eyes, spots) — we kept
    #   them but they're noise for route matching.
    # - prefer skeleton with substantial pixel count (rich silhouette)
    # - mild penalty for very high stroke counts (chaotic drawings)
    # - reward anatomical detail: skeleton endpoints correspond to leg/trunk/tail
    #   tips. 4+ endpoints typically indicates 4 legs (or 4 + trunk/tail). 0
    #   endpoints means a pure closed-loop silhouette (a "potato"-shaped oval
    #   with no protrusions) — those rank among the most "incomplete-looking"
    #   templates. We use a soft saturating bonus so 4-8 endpoints are great
    #   and runaway endpoints (chaotic drawings) don't keep paying out.
    log_asp = math.log(max(0.001, aspect))
    aspect_pen = abs(log_asp - math.log(1.4))
    n_comp = len(keep_labels)
    comp_pen = 0.15 * max(0, n_comp - 3)
    skel_score = min(1.0, skel_px / 500.0)
    stroke_pen = 0.05 * max(0, len(strokes) - 6)
    # Endpoint score: 0 endpoints -> -0.4, 1 -> 0, 4 -> +0.4, saturates beyond 8.
    ep_clipped = min(n_endpoints, 8)
    endpoint_score = 0.1 * (ep_clipped - 1) if ep_clipped >= 1 else -0.4
    score = (
        + 1.2 * skel_score
        - 0.7 * aspect_pen
        - comp_pen
        - stroke_pen
        + endpoint_score
    )

    return Result(
        key_id=key_id,
        category=word,
        points=[(round(x, 5), round(y, 5)) for x, y in points],
        bbox_aspect=aspect,
        n_points=len(points),
        n_strokes=len(strokes),
        n_components_kept=n_comp,
        skeleton_px=skel_px,
        score=float(score),
        reason="ok",
        n_endpoints=n_endpoints,
    )


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data"
    out_root = root / "sketches"
    summary = {}
    for cat in CATEGORIES:
        in_path = data_dir / f"{cat}.recognized.ndjson"
        if not in_path.exists():
            print(f"[{cat}] missing input")
            continue
        cat_dir = out_root / cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        for old in cat_dir.glob("*.json"):
            old.unlink()
        kept: list[Result] = []
        reasons: dict[str, int] = {}
        n_lines = 0
        with in_path.open() as f:
            for line in f:
                n_lines += 1
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                r = extract(rec)
                if r.reason != "ok":
                    reasons[r.reason] = reasons.get(r.reason, 0) + 1
                    continue
                kept.append(r)
        kept.sort(key=lambda r: -r.score)
        top = kept[:TARGET_KEEP]
        for rank, r in enumerate(top):
            payload = {
                "rank": rank,
                "key_id": r.key_id,
                "category": cat,
                "format": "skeleton_pointcloud",
                "n_points": r.n_points,
                "n_strokes": r.n_strokes,
                "n_components_kept": r.n_components_kept,
                "skeleton_px": r.skeleton_px,
                "n_endpoints": r.n_endpoints,
                "bbox_aspect": r.bbox_aspect,
                "score": r.score,
                "points": [list(p) for p in r.points],
            }
            (cat_dir / f"{rank:03d}_{r.key_id}.json").write_text(json.dumps(payload))
        summary[cat] = {
            "input_lines": n_lines,
            "kept": len(kept),
            "saved_top": len(top),
            "reject_reasons": reasons,
        }
        worst = dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:4])
        print(f"[{cat}] in={n_lines} kept={len(kept)} top={len(top)} rejects={worst}")
    (out_root / "extract_summary.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
