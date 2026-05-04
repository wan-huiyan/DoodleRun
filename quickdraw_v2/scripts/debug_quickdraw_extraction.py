"""Diagnose why Quick Draw elephant outlines look 'off'.

Hypothesis: the current extraction picks the longest stroke as the outline,
filters interior strokes by buffered-convex-hull membership, and splices
appendages as out-and-back spikes. For elephants this might be losing
distinctive features (trunk, legs) because:

  - Quick Draw users often draw the elephant's body silhouette as ONE stroke
    that already wraps around all four legs (so the silhouette IS the answer
    and there's no leg-loop appendage to splice). But the RESULT then has no
    legs visible because the user drew abstract leg-bumps, not loops.
  - Some users draw the trunk as a separate appendage stroke. That should be
    spliced. But if the trunk was drawn from a starting point that's INSIDE
    the body's convex hull, the splice attaches at a near-body anchor and the
    out-and-back covers the trunk OK -- but the trunk is then 70%+ inside the
    hull and gets rejected as 'interior detail'.
  - Many sketches have stroke counts > MAX_STROKES (8) and get rejected
    entirely. Quick Draw average stroke count is 5-6, so 8 is fine, but a
    detailed elephant with eyes/ears/etc might have 9+ strokes and become
    a reject without the user knowing.

For each of N high-ranked QD elephant sketches, render a 4-panel diag:
  P1: raw strokes, each color-coded -- shows what the user drew
  P2: longest stroke (main outline) marked, others labeled by hull-fraction
  P3: final extracted polyline rendered standalone
  P4: same polyline overlaid on the original strokes (gray) for comparison
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
import numpy as np
from shapely.geometry import LineString, MultiPoint

# Reuse the extraction pipeline from extract_outlines.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_outlines as eo


def render_strokes(ax, strokes, title, *, highlight_idx=None, hull=None):
    cmap = plt.cm.tab10
    for i, pts in enumerate(strokes):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        color = cmap(i % 10)
        lw = 3.0 if (highlight_idx is not None and i == highlight_idx) else 1.6
        alpha = 1.0 if (highlight_idx is None or i == highlight_idx) else 0.8
        ax.plot(xs, ys, color=color, linewidth=lw, alpha=alpha)
        # Index label at first point.
        ax.annotate(str(i), (xs[0], ys[0]), fontsize=8, color=color,
                    fontweight="bold")
    if hull is not None:
        hxs, hys = hull.exterior.xy
        ax.plot(list(hxs), list(hys), "--", color="black", linewidth=1, alpha=0.4)
    ax.set_aspect("equal")
    ax.invert_yaxis()  # Quick Draw is screen-coords (Y down)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(title, fontsize=9)


def render_polyline(ax, coords, title, bg_strokes=None):
    if bg_strokes:
        for pts in bg_strokes:
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            ax.plot(xs, ys, color="#bbbbbb", linewidth=1.0, alpha=0.7)
    if coords:
        # coords are in normalized [-0.5, 0.5] with Y up. To overlay on raw
        # strokes (which are in pixel space, Y down) we need to denormalize
        # and flip. Skip the overlay if we don't have stroke bbox to align.
        xs = [c[0] for c in coords]; ys = [c[1] for c in coords]
        ax.plot(xs, ys, color="#000", linewidth=2.5)
    ax.set_aspect("equal")
    if bg_strokes:
        ax.invert_yaxis()
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(title, fontsize=9)


def diagnose(rec, out_path: Path):
    drawing = rec.get("drawing", [])
    strokes = [list(zip(s[0], s[1])) for s in drawing if len(s[0]) >= 2]
    if not strokes:
        return False
    perims = [
        sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(s, s[1:]))
        for s in strokes
    ]
    order = sorted(range(len(strokes)), key=lambda i: -perims[i])
    main_idx = order[0]
    main = strokes[main_idx]

    # Compute hull membership for each non-main stroke.
    hull = MultiPoint(main).convex_hull.buffer(eo.HULL_BUFFER_PX)
    inside_fracs = []
    for i, pts in enumerate(strokes):
        if i == main_idx:
            inside_fracs.append(None)
            continue
        try:
            ls = LineString(pts)
            f = ls.intersection(hull).length / max(ls.length, 1e-9)
        except Exception:
            f = -1
        inside_fracs.append(f)

    # Run actual extraction.
    res = eo.extract(rec)
    final_coords = res.coords if (res is not None and res.reason == "ok") else []
    reason = res.reason if res is not None else "none"

    fig, axes = plt.subplots(1, 4, figsize=(20, 4.5))
    n_strokes = len(strokes)
    n_main = len(main)
    title1 = f"P1 raw {n_strokes} strokes (key_id={rec.get('key_id')})"
    render_strokes(axes[0], strokes, title1)

    classifier = []
    for i, f in enumerate(inside_fracs):
        if i == main_idx:
            classifier.append(f"[{i}] MAIN ({n_main} pts, perim={perims[i]:.0f})")
        elif f is None or f < 0:
            classifier.append(f"[{i}] err")
        elif f >= eo.INTERIOR_THRESHOLD:
            classifier.append(f"[{i}] DROP ({f:.0%} inside)")
        else:
            classifier.append(f"[{i}] SPLICE ({f:.0%} inside)")
    title2 = "P2 hull membership\n" + "  ".join(classifier[:4]) + (
        ("\n" + "  ".join(classifier[4:])) if len(classifier) > 4 else "")
    render_strokes(axes[1], strokes, title2,
                   highlight_idx=main_idx, hull=hull)

    title3 = f"P3 final extracted polyline\n(reason={reason}, n_pts={len(final_coords)-1 if final_coords else 0})"
    render_polyline(axes[2], final_coords, title3)

    # P4: overlay (using raw strokes' coordinate space)
    # Re-run a no-normalize extraction so we can overlay on raw strokes.
    overlay_polyline = []
    if res is not None and res.reason == "ok":
        # Reconstruct un-normalized polyline from main + extension splices
        # to render it ON the original sketch.
        polyline = list(main)
        for i, pts in enumerate(strokes):
            if i == main_idx:
                continue
            f = inside_fracs[i]
            if f is None or f < 0 or f >= eo.INTERIOR_THRESHOLD:
                continue
            # Splice as out-and-back spike (mirror of extract logic).
            cands = [pts, list(reversed(pts))]
            best, bd, idx = None, float("inf"), 0
            for c in cands:
                head = c[0]
                for j, p in enumerate(polyline):
                    d = math.hypot(head[0]-p[0], head[1]-p[1])
                    if d < bd:
                        bd, best, idx = d, c, j
            if best is None:
                continue
            polyline = polyline[:idx+1] + list(best) + list(reversed(best)) + polyline[idx+1:]
        if polyline[0] != polyline[-1]:
            polyline.append(polyline[0])
        overlay_polyline = polyline
    if overlay_polyline:
        for pts in strokes:
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            axes[3].plot(xs, ys, color="#bbbbbb", linewidth=1.0, alpha=0.6)
        oxs = [p[0] for p in overlay_polyline]
        oys = [p[1] for p in overlay_polyline]
        axes[3].plot(oxs, oys, color="#d00", linewidth=1.4, alpha=0.85)
        axes[3].set_aspect("equal"); axes[3].invert_yaxis()
        axes[3].set_xticks([]); axes[3].set_yticks([])
        axes[3].set_title("P4 polyline overlay (red = extracted)", fontsize=9)
    else:
        axes[3].set_visible(False)

    fig.tight_layout()
    fig.savefig(out_path, dpi=110, facecolor="white")
    plt.close(fig)
    return True


def main():
    root = Path(__file__).resolve().parent.parent
    raw = root / "data" / "elephant.recognized.ndjson"
    out_dir = root / "diagnostics" / "quickdraw_elephant"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Look at top-30 by score from already-extracted templates so we examine
    # the SAME sketches appearing in the preview grid the user reviewed.
    template_dir = root / "sketches" / "elephant"
    top_key_ids = []
    for f in sorted(template_dir.glob("*.json")):
        d = json.loads(f.read_text())
        if "rank" in d and d["rank"] < 12:   # first 12 (covers user's row 1-2)
            top_key_ids.append(str(d["key_id"]))
    wanted = set(top_key_ids)
    print(f"looking for {len(wanted)} top-ranked sketches in {raw}")

    found = 0
    with raw.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if str(rec.get("key_id")) not in wanted:
                continue
            kid = rec.get("key_id")
            ok = diagnose(rec, out_dir / f"qd_diag_{kid}.png")
            if ok:
                found += 1
                print(f"  -> qd_diag_{kid}.png  ({len(rec.get('drawing',[]))} strokes)")
            if found >= len(wanted):
                break
    print(f"saved {found} diagnostic PNGs to {out_dir}")


if __name__ == "__main__":
    main()
