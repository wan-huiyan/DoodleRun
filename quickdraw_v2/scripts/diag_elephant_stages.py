"""Per-stage diagnostic for Quick Draw elephant extraction.

Renders a 5-panel diagnostic for each suspicious elephant:
  P1: raw strokes (color-coded by stroke index)
  P2: rasterized canvas (after polylines, before close)
  P3: after morphological close
  P4: skeleton
  P5: final point cloud (after component filtering, normalized)

Helps locate at which stage features (trunk/legs/tail) are being lost.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np
from skimage.morphology import skeletonize

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_outlines as eo


def render_strokes(ax, strokes, title):
    cmap = plt.cm.tab10
    for i, (xs, ys) in enumerate(strokes):
        ax.plot(xs, ys, color=cmap(i % 10), linewidth=1.6)
        ax.annotate(str(i), (xs[0], ys[0]), fontsize=8, color=cmap(i % 10),
                    fontweight="bold")
    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(title, fontsize=9)


def render_mask(ax, mask, title):
    ax.imshow(mask, cmap="gray_r", interpolation="nearest")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(title, fontsize=9)


def render_pc(ax, points, title):
    if points:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.scatter(xs, ys, s=0.5, c="black")
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(title, fontsize=9)


def diagnose(rec, out_path: Path):
    drawing = rec.get("drawing", [])
    strokes = []
    for s in drawing:
        if len(s) < 2:
            continue
        xs, ys = s[0], s[1]
        if len(xs) < 2 or len(ys) < 2 or len(xs) != len(ys):
            continue
        strokes.append((list(xs), list(ys)))
    if not strokes:
        return False

    canvas = eo.rasterize_strokes(strokes)
    if eo.CLOSE_PX > 0:
        k = max(3, 2 * eo.CLOSE_PX + 1) | 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        closed = cv2.morphologyEx(canvas, cv2.MORPH_CLOSE, kernel, iterations=1)
    else:
        closed = canvas

    skel = skeletonize(closed > 0).astype(np.uint8)

    res = eo.extract(rec)

    fig, axes = plt.subplots(1, 5, figsize=(22, 4.5))
    title = f"key_id={rec.get('key_id')}  n_strokes={len(strokes)}  reason={res.reason}"
    render_strokes(axes[0], strokes, f"P1 raw strokes\n{title}")
    render_mask(axes[1], canvas, f"P2 rasterized (thick={eo.STROKE_PX}px)")
    render_mask(axes[2], closed, f"P3 after close ({eo.CLOSE_PX}px)")
    render_mask(axes[3], skel * 255, f"P4 skeleton ({int(skel.sum())} px)")
    render_pc(axes[4], res.points if res.reason == "ok" else [],
              f"P5 final pointcloud\nn_pts={res.n_points} n_comp={res.n_components_kept}")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, facecolor="white")
    plt.close(fig)
    return True


def main():
    root = Path(__file__).resolve().parent.parent
    raw = root / "data" / "elephant.recognized.ndjson"
    out_dir = root / "diagnostics" / "elephant_stages"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()

    # Diagnose top-30 to mirror the preview grid the user looked at.
    template_dir = root / "sketches" / "elephant"
    top = []
    for f in sorted(template_dir.glob("*.json")):
        d = json.loads(f.read_text())
        if d.get("rank", 9999) < 30:
            top.append((d["rank"], str(d["key_id"])))
    top.sort()
    wanted = {kid: rank for rank, kid in top}
    print(f"diagnosing {len(wanted)} top elephants")

    found = 0
    with raw.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            kid = str(rec.get("key_id"))
            if kid not in wanted:
                continue
            rank = wanted[kid]
            ok = diagnose(rec, out_dir / f"q{rank:02d}_{kid}.png")
            if ok:
                found += 1
            if found >= len(wanted):
                break
    print(f"saved {found} stage diagnostics to {out_dir}")


if __name__ == "__main__":
    main()
