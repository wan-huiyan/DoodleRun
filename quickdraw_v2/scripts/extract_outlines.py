"""Extract outline + spliced appendages from Quick Draw recognized sketches.

Implements the quickdraw-outline-only-extraction skill:

  1. Sort strokes by perimeter (descending). Longest = main outline.
  2. Buffered convex hull of main outline (6 px on 256-px canvas).
  3. For each non-main stroke:
       fraction-inside = intersection.length / total.length
       >= 70% inside  -> interior detail (eyes/spots/mouth) -> DROP
       <  70% inside  -> appendage extension (tail tip, leg, ear) -> SPLICE
  4. Splice as an OUT-AND-BACK spike at the polyline vertex closest to the
     extension's endpoint. Try both extension orientations, pick the closer.
     This is the right call for GPS-art: real runners do go out-and-back along
     the limb.
  5. Close polyline (last == first).
  6. Validate via Polygon(coords).buffer(0).is_valid — buffer(0) heals the
     self-touching spike vertices.
  7. Normalize to [-0.5, 0.5]^2 (Y up; Quick Draw uses screen-coords Y-down).
  8. Visvalingam-Whyatt simplify to ~36 points using bbox-bound binary search
     on epsilon (vw-simplify-target-point-count skill).

Output: sketches/{category}/<rank>_<key_id>.json
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from shapely.geometry import LineString, MultiPoint, Polygon

try:
    from simplification.cutil import simplify_coords_vw
except Exception:  # pragma: no cover
    simplify_coords_vw = None


CATEGORIES = ["pig", "cat", "dog", "dragon", "duck", "elephant"]

CANVAS_PX = 256.0
HULL_BUFFER_PX = 6.0           # ~2.5% of canvas, per skill defaults
INTERIOR_THRESHOLD = 0.70      # >=70% inside hull => drop
TARGET_POINTS = 36             # closed polyline target
MAX_STROKES = 8


@dataclass
class Result:
    key_id: str
    category: str
    coords: list[tuple[float, float]]
    bbox_aspect: float
    n_points: int
    n_extensions_spliced: int
    main_perimeter_px: float
    score: float
    reason: str = "ok"


# ---------- helpers ---------------------------------------------------------

def stroke_perimeter(stroke):
    xs, ys = stroke[0], stroke[1]
    return sum(math.hypot(xs[i+1]-xs[i], ys[i+1]-ys[i]) for i in range(len(xs)-1))


def vw_to_target(coords: list[tuple[float, float]], target: int,
                 max_iters: int = 30) -> list[tuple[float, float]]:
    """Binary-search VW epsilon to land near `target` points."""
    if simplify_coords_vw is None or len(coords) <= target:
        return coords
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
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


def normalize_unit(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
    w, h = max(xs)-min(xs), max(ys)-min(ys)
    s = max(w, h)
    if s <= 0:
        return None, 0.0
    out = [((p[0]-cx)/s, -(p[1]-cy)/s) for p in pts]
    aspect = w/h if h > 0 else 0.0
    return out, aspect


# ---------- core ------------------------------------------------------------

def extract(rec: dict) -> Optional[Result]:
    drawing = rec.get("drawing")
    if not drawing:
        return Result("?", "?", [], 0, 0, 0, 0, -1, "empty")
    if len(drawing) > MAX_STROKES:
        return Result(rec.get("key_id", "?"), "?", [], 0, 0, 0, 0, -1, "too_many_strokes")

    strokes = []
    for s in drawing:
        if len(s) < 2 or len(s[0]) < 2:
            continue
        pts = list(zip(s[0], s[1]))
        if len(pts) < 2:
            continue
        strokes.append(pts)
    if not strokes:
        return Result(rec.get("key_id", "?"), "?", [], 0, 0, 0, 0, -1, "no_strokes")

    strokes.sort(
        key=lambda pts: -sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(pts, pts[1:]))
    )
    main = list(strokes[0])
    main_perim = sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(main, main[1:]))
    if len(main) < 6 or main_perim < 80:
        return Result(rec.get("key_id", "?"), "?", [], 0, 0, 0, 0, -1, "main_too_small")

    try:
        hull = MultiPoint(main).convex_hull.buffer(HULL_BUFFER_PX)
    except Exception:
        return Result(rec.get("key_id", "?"), "?", [], 0, 0, 0, 0, -1, "hull_failed")

    polyline = list(main)
    n_spliced = 0
    for ext in strokes[1:]:
        try:
            ls = LineString(ext)
        except Exception:
            continue
        if ls.length <= 0:
            continue
        try:
            inside_frac = ls.intersection(hull).length / ls.length
        except Exception:
            continue
        if inside_frac >= INTERIOR_THRESHOLD:
            continue   # interior detail, drop
        # Splice as out-and-back. Try both orientations; pick the closer endpoint.
        cands = [ext, list(reversed(ext))]
        best, bd, idx = None, float("inf"), 0
        for c in cands:
            head = c[0]
            for i, p in enumerate(polyline):
                d = math.hypot(head[0]-p[0], head[1]-p[1])
                if d < bd:
                    bd, best, idx = d, c, i
        if best is None:
            continue
        polyline = polyline[:idx+1] + list(best) + list(reversed(best)) + polyline[idx+1:]
        n_spliced += 1

    if polyline[0] != polyline[-1]:
        polyline.append(polyline[0])

    # Validate after buffer(0) heal (closes spike self-touches).
    try:
        poly = Polygon(polyline).buffer(0)
        if not poly.is_valid or poly.is_empty:
            return Result(rec.get("key_id", "?"), "?", [], 0, 0, n_spliced, main_perim, -1, "polygon_invalid")
    except Exception:
        return Result(rec.get("key_id", "?"), "?", [], 0, 0, n_spliced, main_perim, -1, "polygon_err")

    # Normalize, simplify.
    norm, aspect = normalize_unit(polyline)
    if norm is None:
        return Result(rec.get("key_id", "?"), "?", [], 0, 0, n_spliced, main_perim, -1, "normalize_failed")
    simp = vw_to_target(norm, target=TARGET_POINTS)
    if simp[0] != simp[-1]:
        simp = simp + [simp[0]]

    # Score: prefer
    # - aspect ratio in 0.6..2.5 range (typical for quadruped silhouettes)
    # - 1-3 spliced extensions (tail+legs but not chaotic)
    # - main outline that's substantial (perim >= 200 px on 256 canvas)
    # - vertex count near target
    asp = max(0.001, aspect)
    aspect_pen = abs(math.log(asp) - math.log(1.4))     # peak at 1.4
    ext_score = -abs(n_spliced - 2) * 0.25              # peak at 2 extensions
    perim_score = min(1.0, main_perim / 400.0)
    n_eff = len(simp) - 1
    vert_pen = abs(n_eff - TARGET_POINTS) / TARGET_POINTS

    score = (
        + 1.0 * perim_score
        + ext_score
        - 0.7 * aspect_pen
        - 0.3 * vert_pen
    )

    return Result(
        key_id=str(rec.get("key_id", "?")),
        category=rec.get("word", "?"),
        coords=[(round(x, 5), round(y, 5)) for x, y in simp],
        bbox_aspect=float(aspect),
        n_points=n_eff,
        n_extensions_spliced=n_spliced,
        main_perimeter_px=float(main_perim),
        score=float(score),
        reason="ok",
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
        # Wipe prior outputs from earlier (incorrect) extraction runs.
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
                if r is None or r.reason != "ok":
                    reason = "none" if r is None else r.reason
                    reasons[reason] = reasons.get(reason, 0) + 1
                    continue
                kept.append(r)
        kept.sort(key=lambda r: -r.score)
        top = kept[:200]
        for rank, r in enumerate(top):
            payload = {
                "rank": rank,
                "key_id": r.key_id,
                "category": cat,
                "n_points": r.n_points,
                "bbox_aspect": r.bbox_aspect,
                "n_extensions_spliced": r.n_extensions_spliced,
                "main_perimeter_px": r.main_perimeter_px,
                "score": r.score,
                "coords": [list(p) for p in r.coords],
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
