"""Convert an SVG cartoon/silhouette into a normalized DoodleRun outline.

Two strategies:

* `--mode single` (default) — pick one sub-path (largest non-bg-rect by
  bbox diagonal, or `--path-index N` to override) and trace it. Good for
  silhouette SVGs where the outer outline is one closed path.

* `--mode union` — sample the top `--top-n` sub-paths into polygons and
  shapely-union them, then take the exterior of the largest piece. Good
  for cartoon SVGs where body/head/legs/tail are separate paths and we
  want their silhouette merged into one kawaii blob.

After the source-coordinate outline is picked, both modes share the
finishing pipeline:

1. Sample by arc length / use shapely exterior.
2. Ramer-Douglas-Peucker simplification (~30-70 points).
3. Y-flip (SVG y-down → math y-up).
4. Optional X-flip to face right.
5. Translate to origin, scale to target width.
"""
from __future__ import annotations

import argparse
import math
from typing import List, Tuple

from svgpathtools import svg2paths2

Point = Tuple[float, float]


def sample_path(path, n: int) -> List[Point]:
    """Sample n points along a path uniformly by arc length."""
    out: List[Point] = []
    total = path.length()
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0
        z = path.point(path.ilength(t * total))
        out.append((z.real, z.imag))
    return out


def perpendicular_distance(p: Point, a: Point, b: Point) -> float:
    """Perpendicular distance from p to line segment ab."""
    if a == b:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    num = abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1]))
    den = math.hypot(b[0] - a[0], b[1] - a[1])
    return num / den


def rdp(points: List[Point], epsilon: float) -> List[Point]:
    """Ramer-Douglas-Peucker polyline simplification."""
    if len(points) < 3:
        return points[:]
    dmax = 0.0
    index = 0
    for i in range(1, len(points) - 1):
        d = perpendicular_distance(points[i], points[0], points[-1])
        if d > dmax:
            dmax = d
            index = i
    if dmax > epsilon:
        left = rdp(points[:index + 1], epsilon)
        right = rdp(points[index:], epsilon)
        return left[:-1] + right
    return [points[0], points[-1]]


def normalize(points: List[Point], target_w: float, flip_x: bool, flip_y: bool) -> List[Point]:
    """Y-flip (SVG → math), optional X-flip, translate to origin, scale to target_w."""
    if flip_y:
        points = [(x, -y) for (x, y) in points]
    if flip_x:
        points = [(-x, y) for (x, y) in points]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    w = max_x - min_x
    scale = target_w / w
    return [((x - min_x) * scale, (y - min_y) * scale) for x, y in points]


def _bbox_diag(path) -> float:
    try:
        xmin, xmax, ymin, ymax = path.bbox()
    except Exception:
        return 0.0
    return math.hypot(xmax - xmin, ymax - ymin)


def _is_bg_rect(s) -> bool:
    """Detect axis-aligned rectangle paths (canvas background frames).

    Heuristic: arc length matches bbox perimeter to within 3%. These
    almost always come from <rect> background fills converted to paths
    and would otherwise dominate the bbox-diag ranking on cartoon SVGs.
    """
    try:
        xmin, xmax, ymin, ymax = s.bbox()
    except Exception:
        return False
    bw, bh = xmax - xmin, ymax - ymin
    if bw == 0 or bh == 0:
        return False
    try:
        length = s.length()
    except Exception:
        return False
    peri = 2 * (bw + bh)
    return peri > 0 and abs(length - peri) / peri < 0.03


def collect_subpaths(svg_path: str):
    """Flatten an SVG into all continuous sub-paths, skipping bg rects."""
    paths, _, _ = svg2paths2(svg_path)
    subs = []
    for p in paths:
        try:
            ss = p.continuous_subpaths() if hasattr(p, "continuous_subpaths") else [p]
        except Exception:
            ss = [p]
        subs.extend(ss)
    safe = [s for s in subs if _bbox_diag(s) > 0 and not _is_bg_rect(s)]
    safe.sort(key=_bbox_diag, reverse=True)
    return safe


def convert(svg_path: str, n_sample: int, rdp_eps: float,
            target_w: float, flip_x: bool, flip_y: bool,
            path_index: int = 0) -> List[Point]:
    """Single-path mode: pick the (path_index)th sub-path by bbox-diag-
    descending after filtering out background rectangles, sample it, RDP-
    simplify, then normalize. path_index=0 == default longest-non-bg sub-
    path."""
    safe = collect_subpaths(svg_path)
    if not safe:
        raise ValueError(f"no usable sub-paths in {svg_path}")
    if path_index >= len(safe):
        raise IndexError(f"path-index {path_index} out of range "
                         f"(only {len(safe)} non-bg sub-paths)")
    main = safe[path_index]
    sampled = sample_path(main, n_sample)
    return _finish(sampled, rdp_eps, target_w, flip_x, flip_y)


def convert_union(svg_path: str, top_n: int, n_sample: int, rdp_eps: float,
                  target_w: float, flip_x: bool, flip_y: bool,
                  area_min_frac: float = 0.005) -> List[Point]:
    """Union-mode: sample the top `top_n` non-bg sub-paths into polygons,
    shapely-union them, take the exterior of the largest resulting piece,
    then RDP-simplify and normalize. Use this for cartoon SVGs where
    body/head/legs/tail are separate paths whose silhouette we want
    merged into one kawaii blob."""
    from shapely.geometry import Polygon, MultiPolygon
    from shapely.ops import unary_union

    safe = collect_subpaths(svg_path)
    if not safe:
        raise ValueError(f"no usable sub-paths in {svg_path}")
    biggest_area = (_bbox_diag(safe[0]) ** 2) or 1.0
    polys = []
    for s in safe[:top_n]:
        try:
            pts = sample_path(s, n_sample)
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            if poly.area < area_min_frac * biggest_area:
                continue
            polys.append(poly)
        except Exception:
            continue
    if not polys:
        raise ValueError(f"no valid polygons after sampling {svg_path}")
    u = unary_union(polys)
    if isinstance(u, MultiPolygon):
        u = max(u.geoms, key=lambda p: p.area)
    pts = list(u.exterior.coords)
    return _finish(pts, rdp_eps, target_w, flip_x, flip_y)


def _finish(pts: List[Point], rdp_eps: float, target_w: float,
            flip_x: bool, flip_y: bool) -> List[Point]:
    """Shared tail of single + union modes: RDP simplify, ensure closed,
    then normalize (flip + translate to origin + scale to target width)."""
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    eps_units = rdp_eps * diag
    simplified = rdp(pts, eps_units)
    if simplified[0] != simplified[-1]:
        simplified.append(simplified[0])
    return normalize(simplified, target_w, flip_x, flip_y)


def extract_interior_features(
    svg_path: str,
    outline_index: int = 0,
    n_sample_per_feature: int = 24,
    rdp_eps: float = 0.012,
    max_size_frac: float = 0.4,
    min_size_frac: float = 0.005,
) -> List[List[Point]]:
    """Generic interior-stroke extraction.

    Returns a list of polylines (each a list of (x, y) points in SVG source
    coordinates — caller is responsible for the same y-flip / x-flip /
    scale that was applied to the outline).

    Heuristic, not animal-specific: every non-background sub-path that
    is NOT the chosen outline AND whose bounding box is meaningfully
    smaller than the outline's bounding box is treated as an interior
    feature. Whiskers, nostrils, eyes, mouth lines, fur tufts — whatever
    the SVG's interior detail strokes are — get picked up uniformly.

    Args:
      outline_index: which sub-path is the outline (so we skip it).
      max_size_frac: features bigger than this fraction of the outline's
        bbox-diag are treated as additional silhouettes, not interior
        details, and dropped.
      min_size_frac: features below this size are treated as noise.
    """
    safe = collect_subpaths(svg_path)
    if outline_index >= len(safe):
        return []
    outline_diag = _bbox_diag(safe[outline_index])
    if outline_diag == 0:
        return []
    features: List[List[Point]] = []
    for i, s in enumerate(safe):
        if i == outline_index:
            continue
        d = _bbox_diag(s)
        if d == 0:
            continue
        ratio = d / outline_diag
        if ratio > max_size_frac or ratio < min_size_frac:
            continue
        try:
            pts = sample_path(s, n_sample_per_feature)
        except Exception:
            continue
        local_diag = math.hypot(
            max(p[0] for p in pts) - min(p[0] for p in pts),
            max(p[1] for p in pts) - min(p[1] for p in pts),
        )
        if local_diag == 0:
            continue
        eps_units = rdp_eps * local_diag
        simplified = rdp(pts, eps_units)
        if len(simplified) >= 2:
            features.append(simplified)
    return features


def normalize_features(
    features: List[List[Point]],
    outline_raw: List[Point],
    outline_normalized: List[Point],
    flip_x: bool,
    flip_y: bool,
) -> List[List[Point]]:
    """Apply the same flip + translate + scale the outline received, so
    interior features stay registered to the outline. Computes the affine
    from raw → normalized outline bboxes and applies it to every feature.
    """
    if not features:
        return []
    # Apply flips first (matching what `normalize` does to the outline)
    flipped: List[List[Point]] = []
    for feat in features:
        ff = feat
        if flip_y:
            ff = [(x, -y) for (x, y) in ff]
        if flip_x:
            ff = [(-x, y) for (x, y) in ff]
        flipped.append(ff)

    # Compute outline raw (post-flip) bbox vs. normalized bbox to get scale + offset
    raw = outline_raw
    if flip_y:
        raw = [(x, -y) for (x, y) in raw]
    if flip_x:
        raw = [(-x, y) for (x, y) in raw]
    rmin_x = min(p[0] for p in raw); rmax_x = max(p[0] for p in raw)
    rmin_y = min(p[1] for p in raw); rmax_y = max(p[1] for p in raw)
    nmin_x = min(p[0] for p in outline_normalized); nmax_x = max(p[0] for p in outline_normalized)
    nmin_y = min(p[1] for p in outline_normalized); nmax_y = max(p[1] for p in outline_normalized)
    raw_w = rmax_x - rmin_x or 1.0
    scale = (nmax_x - nmin_x) / raw_w
    out: List[List[Point]] = []
    for feat in flipped:
        out.append([
            ((x - rmin_x) * scale + nmin_x,
             (y - rmin_y) * scale + nmin_y)
            for (x, y) in feat
        ])
    return out


def format_outline(points: List[Point], indent: str = "    ") -> str:
    lines = []
    for x, y in points:
        lines.append(f"{indent}({x:.2f}, {y:.2f}),")
    return "[\n" + "\n".join(lines) + "\n]"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("--n-sample", type=int, default=200,
                    help="Initial dense sample count before RDP")
    ap.add_argument("--rdp-eps", type=float, default=0.012,
                    help="RDP epsilon as fraction of bbox diagonal "
                         "(0.005=fine detail, 0.02=very coarse)")
    ap.add_argument("--target-w", type=float, default=12.0,
                    help="Output width in shape units")
    ap.add_argument("--flip-x", action="store_true",
                    help="Mirror horizontally (use to make animal face right)")
    ap.add_argument("--no-flip-y", action="store_true",
                    help="Skip the SVG y-down → math y-up flip")
    ap.add_argument("--path-index", type=int, default=0,
                    help="Pick the Nth sub-path after sorting non-bg-rect "
                         "sub-paths by bbox diagonal descending (default 0).")
    ap.add_argument("--mode", choices=["single", "union"], default="single",
                    help="single: trace one sub-path. union: shapely-union "
                         "the top --top-n sub-paths and trace the result.")
    ap.add_argument("--top-n", type=int, default=20,
                    help="Union mode: how many largest sub-paths to merge.")
    ap.add_argument("--with-interior", action="store_true",
                    help="Also extract interior-feature strokes (small "
                         "sub-paths inside the outline). Emits a second "
                         "INTERIOR_FEATURES list after OUTLINE.")
    args = ap.parse_args()

    if args.mode == "union":
        pts = convert_union(args.svg, args.top_n, args.n_sample, args.rdp_eps,
                            args.target_w, args.flip_x, not args.no_flip_y)
    else:
        pts = convert(args.svg, args.n_sample, args.rdp_eps, args.target_w,
                      args.flip_x, not args.no_flip_y, args.path_index)
    print(f"# {len(pts)} points")
    print("OUTLINE = " + format_outline(pts))

    if args.with_interior and args.mode == "single":
        # Re-collect raw outline + features in the SVG's own coords for
        # accurate registration after normalization.
        safe = collect_subpaths(args.svg)
        raw_outline = sample_path(safe[args.path_index], args.n_sample)
        features_raw = extract_interior_features(
            args.svg,
            outline_index=args.path_index,
            n_sample_per_feature=max(24, args.n_sample // 4),
            rdp_eps=args.rdp_eps,
        )
        features_norm = normalize_features(
            features_raw, raw_outline, pts,
            args.flip_x, not args.no_flip_y,
        )
        print(f"\n# {len(features_norm)} interior feature(s)")
        print("INTERIOR_FEATURES = [")
        for f in features_norm:
            print("    " + format_outline(f, indent="        ") + ",")
        print("]")
