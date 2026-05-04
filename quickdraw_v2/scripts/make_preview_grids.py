"""Render numbered preview grids combining Quick Draw + strav.art templates per animal.

For each animal we produce two grids:
  previews/{animal}_quickdraw.png   — top 30 QD outlines, labelled Q01..Q30
  previews/{animal}_stravart.png    — top 30 strav.art outlines, labelled S01..S30
plus a combined contact sheet:
  previews/{animal}_combined.png    — both stacked, easier for voting

Each cell shows the closed normalized polyline as a thick black line on white,
plus the vote ID, score, vertex count, and aspect ratio.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon
import numpy as np

CATEGORIES = ["pig", "cat", "dog", "dragon", "duck", "elephant"]
GRID_COLS = 6
GRID_ROWS = 5  # -> 30 per source
CELL_W_IN = 1.6
CELL_H_IN = 1.6


def load_templates(dir_: Path, top_n: int):
    items = []
    if not dir_.exists():
        return items
    for jp in sorted(dir_.glob("*.json")):
        if jp.name == "extract_summary.json":
            continue
        try:
            d = json.loads(jp.read_text())
        except Exception:
            continue
        items.append(d)
    items.sort(key=lambda x: -x.get("score", 0))
    return items[:top_n]


def _draw_template(ax, d):
    """Render either a closed-polygon (Quick Draw) or skeleton point cloud (strav.art)."""
    fmt = d.get("format")
    if fmt == "skeleton_pointcloud" or "points" in d:
        pts = d["points"]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        # Dot size scaled so 4000 dots fill the 1.6" cell visually.
        size = max(0.3, min(1.5, 800.0 / max(len(pts), 1)))
        ax.scatter(xs, ys, s=size, c="#111", marker=".", linewidths=0)
    else:
        coords = d["coords"]
        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        poly = MplPolygon(
            list(zip(xs, ys)),
            closed=True,
            facecolor="#f3f3f3",
            edgecolor="#111",
            linewidth=2.0,
            joinstyle="round",
        )
        ax.add_patch(poly)


def render_grid(items, animal: str, prefix: str, title_suffix: str, out_path: Path):
    rows = GRID_ROWS
    cols = GRID_COLS
    n = rows * cols
    items = items[:n]
    fig, axes = plt.subplots(
        rows, cols, figsize=(cols * CELL_W_IN, rows * CELL_H_IN + 0.6)
    )
    if rows == 1:
        axes = [axes]
    for i in range(n):
        ax = axes[i // cols][i % cols]
        ax.set_xlim(-0.6, 0.6)
        ax.set_ylim(-0.6, 0.6)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color("#cccccc")
        if i >= len(items):
            ax.set_visible(False)
            continue
        d = items[i]
        _draw_template(ax, d)
        vid = f"{animal[:3].upper()}-{prefix}{i+1:02d}"
        npts = d.get("n_points", "?")
        asp = d.get("bbox_aspect", 0)
        score = d.get("score", 0)
        ax.set_title(
            f"{vid}\nn={npts} ar={asp:.2f} sc={score:+.2f}",
            fontsize=7,
            pad=2,
        )
    fig.suptitle(
        f"{animal.upper()} — {title_suffix} (vote IDs {animal[:3].upper()}-{prefix}01..{prefix}{n:02d})",
        fontsize=12,
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, facecolor="white")
    plt.close(fig)


def render_combined(qd_items, sa_items, animal: str, out_path: Path):
    rows = GRID_ROWS * 2
    cols = GRID_COLS
    cells = rows * cols
    fig, axes = plt.subplots(
        rows, cols, figsize=(cols * CELL_W_IN, rows * CELL_H_IN + 1.0)
    )
    half = GRID_ROWS * cols
    for i in range(cells):
        ax = axes[i // cols][i % cols]
        ax.set_xlim(-0.6, 0.6)
        ax.set_ylim(-0.6, 0.6)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        if i < half:
            d = qd_items[i] if i < len(qd_items) else None
            prefix = "Q"
            band = "#ffeede"   # warm tint for Quick Draw
            local_i = i
        else:
            d = sa_items[i - half] if (i - half) < len(sa_items) else None
            prefix = "S"
            band = "#deecff"   # cool tint for strav.art
            local_i = i - half
        ax.set_facecolor(band)
        for spine in ax.spines.values():
            spine.set_color("#bbbbbb")
        if d is None:
            ax.set_visible(False)
            continue
        _draw_template(ax, d)
        vid = f"{animal[:3].upper()}-{prefix}{local_i+1:02d}"
        npts = d.get("n_points", "?")
        asp = d.get("bbox_aspect", 0)
        ax.set_title(f"{vid}\nn={npts}  ar={asp:.2f}", fontsize=7, pad=2)
    fig.suptitle(
        f"{animal.upper()} — top 30 Quick Draw (warm, Q01–Q30) + top 30 strav.art (cool, S01–S30)\n"
        f"Vote with IDs like {animal[:3].upper()}-Q05, {animal[:3].upper()}-S12",
        fontsize=12,
        y=0.995,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, facecolor="white")
    plt.close(fig)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    qd_root = root / "sketches"
    sa_root = root / "templates_strav"
    out_root = root / "previews"
    out_root.mkdir(parents=True, exist_ok=True)

    for cat in CATEGORIES:
        n = GRID_COLS * GRID_ROWS
        qd_items = load_templates(qd_root / cat, n)
        sa_items = load_templates(sa_root / cat, n)
        if qd_items:
            render_grid(qd_items, cat, "Q", f"top {len(qd_items)} Quick Draw outlines",
                        out_root / f"{cat}_quickdraw.png")
        if sa_items:
            render_grid(sa_items, cat, "S", f"top {len(sa_items)} strav.art templates",
                        out_root / f"{cat}_stravart.png")
        if qd_items or sa_items:
            render_combined(qd_items, sa_items, cat, out_root / f"{cat}_combined.png")
        print(f"[{cat}] qd={len(qd_items)} sa={len(sa_items)} -> {out_root}/{cat}_*.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
