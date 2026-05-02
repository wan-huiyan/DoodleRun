"""Convert an SVG cartoon/silhouette into a normalized DoodleRun outline.

Two strategies:

* `--mode single` (default) — pick one sub-path (largest non-bg-rect by
  bbox diagonal, or `--path-index N` to override) and trace it. Good for
  silhouette SVGs where the outer outline is one closed path.

* `--mode union` — sample the top `--top-n` sub-paths into polygons and
  shapely-union them, then take the exterior of the largest piece. Good
  for cartoon SVGs where body/head/legs/tail are separate paths.

Both modes share the finishing pipeline:

1. Sample by arc length / use shapely exterior.
2. Simplify to roughly `--target-points` (Visvalingam-Whyatt by default;
   RDP available with `--simplify rdp`).
3. Validate (no self-intersections, sane aspect ratio).
4. Y-flip (SVG y-down → math y-up).
5. Optional X-flip to face right.
6. Translate to origin, scale to target width.

`--with-interior` works in both modes — it pulls out small sub-paths
that fall inside the outline (whiskers, nostrils, eyes) and emits them
as a second INTERIOR_FEATURES list.
"""
from __future__ import annotations

import argparse
import math
import os
from typing import List, Optional, Tuple

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


def vw_simplify(points: List[Point], target_points: int) -> List[Point]:
    """Visvalingam-Whyatt simplification down to roughly `target_points`.

    VW preserves visual area (removes the smallest-triangle vertex first),
    which is perceptually better for rounded animal shapes than RDP's
    perpendicular-distance metric. Section 4.2 of the overhaul plan
    recommends VW as the default.

    Falls back to a small pure-Python implementation if the Rust-backed
    `simplification` package isn't available — this means the script
    still works in minimal environments, just slower for large inputs.
    """
    if target_points < 2 or len(points) <= target_points:
        return points[:]
    try:
        from simplification.cutil import simplify_coords_vw  # type: ignore
        # The library wants a number of points to KEEP — it interprets
        # the parameter exactly that way when given an int via
        # `simplify_coords_vw_idx`. We use the threshold-based variant
        # and binary-search the threshold to hit the target count.
        # Easier: use the rust-backed simplify_coords_vwp which keeps
        # visvalingam triangulation valid; iterate threshold to land
        # near target_points.
        return _vw_to_target(points, target_points)
    except Exception:
        return _vw_python(points, target_points)


def _vw_to_target(points: List[Point], target: int) -> List[Point]:
    """Iterative-threshold VW: keep raising epsilon until the simplified
    polyline has approximately `target` points. Caps at 30 attempts."""
    from simplification.cutil import simplify_coords_vw  # type: ignore
    # Estimate a starting epsilon from the bbox area.
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    bbox_area = (max(xs) - min(xs)) * (max(ys) - min(ys)) or 1.0
    lo, hi = 0.0, bbox_area
    best = list(points)
    for _ in range(30):
        mid = (lo + hi) / 2 if hi > lo else hi
        if mid == 0:
            return points[:]
        try:
            simp = simplify_coords_vw(points, mid)
        except Exception:
            return _vw_python(points, target)
        if len(simp) == target:
            return [tuple(p) for p in simp]
        if len(simp) > target:
            lo = mid
            best = simp
        else:
            hi = mid
            if abs(len(simp) - target) < abs(len(best) - target):
                best = simp
    return [tuple(p) for p in best]


def _vw_python(points: List[Point], target: int) -> List[Point]:
    """Pure-Python VW fallback. O(n²); fine for outlines under 500 points."""
    pts = list(points)
    while len(pts) > target:
        # Triangle area for each interior vertex i: |((b-a)×(c-a))/2|.
        smallest_i = -1
        smallest_area = float("inf")
        for i in range(1, len(pts) - 1):
            a, b, c = pts[i - 1], pts[i], pts[i + 1]
            area = abs((b[0] - a[0]) * (c[1] - a[1])
                       - (c[0] - a[0]) * (b[1] - a[1])) * 0.5
            if area < smallest_area:
                smallest_area = area
                smallest_i = i
        if smallest_i < 0:
            break
        del pts[smallest_i]
    return pts


def validate_outline(points: List[Point]) -> Tuple[bool, List[str]]:
    """Sanity-check the simplified outline before emitting it.

    Returns (ok, warnings). Doesn't raise — the caller decides whether to
    bail or just print warnings. Checks per Section 4.2 of the plan:
    * polygon validity (no self-intersections),
    * bounding-box aspect ratio in a plausible range.
    """
    warnings: List[str] = []
    if len(points) < 4:
        return False, ["outline has fewer than 4 vertices"]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    w = max(xs) - min(xs) or 1e-9
    h = max(ys) - min(ys) or 1e-9
    aspect = w / h
    if aspect < 0.3 or aspect > 3.0:
        warnings.append(f"unusual aspect ratio {aspect:.2f} (expected 0.3..3.0)")
    try:
        from shapely.geometry import Polygon  # type: ignore
        poly = Polygon(points)
        if not poly.is_valid:
            warnings.append("polygon is not simple (self-intersections)")
        if poly.area <= 0:
            warnings.append("polygon area is zero or negative")
    except Exception:
        pass
    return (not any("not simple" in w or "fewer than" in w for w in warnings),
            warnings)


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


def convert(svg_path: str, n_sample: int, target_points: int,
            target_w: float, flip_x: bool, flip_y: bool,
            path_index: int = 0,
            simplify: str = "vw",
            rdp_eps: float = 0.012) -> List[Point]:
    """Single-path mode: pick the (path_index)th sub-path by bbox-diag-
    descending after filtering out background rectangles, sample it,
    simplify, then normalize."""
    safe = collect_subpaths(svg_path)
    if not safe:
        raise ValueError(f"no usable sub-paths in {svg_path}")
    if path_index >= len(safe):
        raise IndexError(f"path-index {path_index} out of range "
                         f"(only {len(safe)} non-bg sub-paths)")
    main = safe[path_index]
    sampled = sample_path(main, n_sample)
    return _finish(sampled, target_points, target_w, flip_x, flip_y,
                   simplify=simplify, rdp_eps=rdp_eps)


def convert_union(svg_path: str, top_n: int, n_sample: int,
                  target_points: int, target_w: float,
                  flip_x: bool, flip_y: bool,
                  area_min_frac: float = 0.005,
                  simplify: str = "vw",
                  rdp_eps: float = 0.012) -> List[Point]:
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
    return _finish(pts, target_points, target_w, flip_x, flip_y,
                   simplify=simplify, rdp_eps=rdp_eps)


def _finish(pts: List[Point], target_points: int, target_w: float,
            flip_x: bool, flip_y: bool,
            simplify: str = "vw",
            rdp_eps: float = 0.012) -> List[Point]:
    """Shared tail of single + union modes: simplify, ensure closed,
    normalize (flip + translate to origin + scale to target width)."""
    if simplify == "rdp":
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        eps_units = rdp_eps * diag
        simplified = rdp(pts, eps_units)
    else:
        simplified = vw_simplify(pts, target_points)
    if not simplified:
        simplified = pts[:]
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


def _emit_shape_file(family: str,
                     outline: List[Point],
                     interior: List[List[Point]],
                     metadata: dict,
                     out_stream) -> None:
    """Emit a complete `<family>_shape.py` source file. Writing this rather
    than just OUTLINE = [...] makes the SVG → registry pipeline a one-shot
    `python tools/svg_to_shape.py … --output prototype/<family>_shape.py`
    drop-in (Section 4.3 of the plan: pipeline for non-animal shapes)."""
    print(f'"""{family.capitalize()} outline — generated by tools/svg_to_shape.py."""', file=out_stream)
    print("", file=out_stream)
    print("from __future__ import annotations", file=out_stream)
    print("", file=out_stream)
    print("from typing import List", file=out_stream)
    print("", file=out_stream)
    print("from shape_utils import Point", file=out_stream)
    print("", file=out_stream)
    print(f"OUTLINE: List[Point] = {format_outline(outline)}", file=out_stream)
    print("", file=out_stream)
    print("INTERIOR_FEATURES: List[List[Point]] = [", file=out_stream)
    for f in interior:
        print("    " + format_outline(f, indent="        ") + ",", file=out_stream)
    print("]", file=out_stream)
    print("", file=out_stream)
    print(f"METADATA = {metadata!r}", file=out_stream)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("--n-sample", type=int, default=200,
                    help="Initial dense sample count before simplification")
    ap.add_argument("--simplify", choices=["vw", "rdp"], default="vw",
                    help="Simplification method. VW (Visvalingam-Whyatt) "
                         "preserves visual area and is the default. RDP is "
                         "kept for legacy callers.")
    ap.add_argument("--target-points", type=int, default=40,
                    help="Target number of OUTLINE points after VW "
                         "simplification (default 40). Ignored if "
                         "--simplify rdp.")
    ap.add_argument("--rdp-eps", type=float, default=0.012,
                    help="RDP epsilon as fraction of bbox diagonal "
                         "(0.005=fine detail, 0.02=very coarse). Only used "
                         "when --simplify rdp.")
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
                         "sub-paths inside the outline). Works in both "
                         "single and union modes.")
    ap.add_argument("--output", "-o", default=None,
                    help="Path to write a full <family>_shape.py file. If "
                         "omitted, prints OUTLINE = [...] to stdout.")
    ap.add_argument("--family", default=None,
                    help="Family name for the output file's METADATA block. "
                         "Defaults to the SVG's basename without extension.")
    ap.add_argument("--source", default=None,
                    help="Source description embedded in METADATA")
    ap.add_argument("--license", default="unknown",
                    help="License string embedded in METADATA")
    args = ap.parse_args()

    if args.mode == "union":
        pts = convert_union(args.svg, args.top_n, args.n_sample,
                            target_points=args.target_points,
                            target_w=args.target_w,
                            flip_x=args.flip_x, flip_y=not args.no_flip_y,
                            simplify=args.simplify, rdp_eps=args.rdp_eps)
    else:
        pts = convert(args.svg, args.n_sample,
                      target_points=args.target_points,
                      target_w=args.target_w,
                      flip_x=args.flip_x, flip_y=not args.no_flip_y,
                      path_index=args.path_index,
                      simplify=args.simplify, rdp_eps=args.rdp_eps)

    ok, warnings = validate_outline(pts)
    for w in warnings:
        print(f"# WARN: {w}")
    if not ok:
        print("# ERROR: outline failed validation; refusing to emit shape file")
        raise SystemExit(2)

    interior_norm: List[List[Point]] = []
    if args.with_interior:
        # Both modes need the raw outline in SVG-source coords for
        # registering interior features after the normalize-to-target_w
        # transform. In `union` mode the chosen "outline" is the union
        # exterior, which has no single source sub-path — we use the
        # largest sub-path's raw samples as the registration anchor (the
        # union's exterior is a superset of it, so the bbox-driven affine
        # in normalize_features still produces a sensible registration).
        safe = collect_subpaths(args.svg)
        anchor_idx = args.path_index if args.mode == "single" else 0
        raw_outline = sample_path(safe[anchor_idx], args.n_sample)
        features_raw = extract_interior_features(
            args.svg,
            outline_index=anchor_idx,
            n_sample_per_feature=max(24, args.n_sample // 4),
            rdp_eps=args.rdp_eps,
        )
        interior_norm = normalize_features(
            features_raw, raw_outline, pts,
            args.flip_x, not args.no_flip_y,
        )

    if args.output:
        family = args.family or os.path.splitext(os.path.basename(args.svg))[0]
        metadata = {
            "description": f"{family.capitalize()} outline derived from {os.path.basename(args.svg)}",
            "source": args.source or args.svg,
            "license": args.license,
        }
        with open(args.output, "w") as f:
            _emit_shape_file(family, pts, interior_norm, metadata, f)
        print(f"# wrote {args.output}: {len(pts)} outline points, "
              f"{len(interior_norm)} interior feature(s)")
    else:
        print(f"# {len(pts)} points")
        print("OUTLINE = " + format_outline(pts))
        if interior_norm:
            print(f"\n# {len(interior_norm)} interior feature(s)")
            print("INTERIOR_FEATURES = [")
            for f in interior_norm:
                print("    " + format_outline(f, indent="        ") + ",")
            print("]")
