"""Convert an SVG silhouette into a normalized DoodleRun shape outline.

Pipeline:
1. Pick the longest path in the SVG (the main outer outline).
2. Sample N points uniformly by arc-length.
3. Apply Ramer-Douglas-Peucker simplification so we end up with ~40-60
   points that capture the silhouette without redundancy.
4. Y-flip (SVG is y-down, our shape is y-up).
5. Optional X-flip so the animal faces right (controlled per-shape).
6. Translate to origin (min x, min y at zero), then optionally scale to
   target width.

The output is printed as a Python list literal ready to paste into a
shape file.
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
    xmin, xmax, ymin, ymax = path.bbox()
    return math.hypot(xmax - xmin, ymax - ymin)


def convert(svg_path: str, n_sample: int, rdp_eps: float,
            target_w: float, flip_x: bool, flip_y: bool) -> List[Point]:
    paths, attrs, _ = svg2paths2(svg_path)
    # Longest path = main outline (smaller paths are usually eyes/mouth).
    main = max(paths, key=lambda p: p.length())
    # Many SVG silhouettes pack the outer outline + interior holes (eye,
    # mouth) into a single path with `M` (move) commands separating sub-
    # paths. Sampling the joined path produces phantom straight lines
    # connecting the sub-shapes. Split and keep only the OUTER sub-path,
    # identified by largest bbox diagonal.
    subs = main.continuous_subpaths() if hasattr(main, "continuous_subpaths") else [main]
    main = max(subs, key=_bbox_diag)
    sampled = sample_path(main, n_sample)
    # RDP works in source units; epsilon is a fraction of bbox diagonal.
    xs = [p[0] for p in sampled]; ys = [p[1] for p in sampled]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    eps_units = rdp_eps * diag
    simplified = rdp(sampled, eps_units)
    # Ensure closed.
    if simplified[0] != simplified[-1]:
        simplified.append(simplified[0])
    return normalize(simplified, target_w, flip_x, flip_y)


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
    args = ap.parse_args()

    pts = convert(args.svg, args.n_sample, args.rdp_eps, args.target_w,
                  args.flip_x, not args.no_flip_y)
    print(f"# {len(pts)} points")
    print(format_outline(pts))
