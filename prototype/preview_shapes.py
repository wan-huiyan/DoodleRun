"""Render pure-shape PNG previews for each animal outline.

No street map, no routing — just the polyline + numbered anchor markers,
on a clean white canvas. This is the "thumbnail squint test": if you can't
tell what animal it is from this picture, the router can't possibly turn
it into recognizable GPS art.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from cat_shape import CAT_OUTLINE
from chicken_shape import CHICKEN_OUTLINE
from dino_shape import DINO_OUTLINE
from dog_shape import DOG_OUTLINE
from pig_shape import PIG_OUTLINE

SHAPES = {
    "pig": PIG_OUTLINE,
    "cat": CAT_OUTLINE,
    "dog": DOG_OUTLINE,
    "dino": DINO_OUTLINE,
    "chicken": CHICKEN_OUTLINE,
}


def render_shape(name: str, points, out_dir: Path) -> Path:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    fig, ax = plt.subplots(figsize=(7, 7), dpi=140)
    ax.plot(xs, ys, color="#1f77b4", linewidth=4.5, solid_capstyle="round",
            solid_joinstyle="round")
    ax.scatter(xs[:-1], ys[:-1], color="#d62728", s=70, zorder=5,
               edgecolors="white", linewidths=1.5)
    for i, (x, y) in enumerate(points[:-1], start=1):
        ax.annotate(str(i), (x, y), textcoords="offset points",
                    xytext=(8, 6), fontsize=9, color="#444", weight="bold")

    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title(f"{name.upper()}  —  {len(points) - 1} anchors",
                 fontsize=14, weight="bold")
    ax.grid(True, linestyle=":", alpha=0.3)
    ax.set_facecolor("white")

    bbox = ax.get_xlim(), ax.get_ylim()
    pad = 0.8
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)

    out_path = out_dir / f"{name}_shape.png"
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


def render_thumbnail_grid(out_dir: Path) -> Path:
    """Render all 5 shapes side-by-side at thumbnail size — the squint test."""
    fig, axes = plt.subplots(1, 5, figsize=(20, 4.5), dpi=140)
    for ax, (name, points) in zip(axes, SHAPES.items()):
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(xs, ys, color="#1f77b4", linewidth=4, solid_capstyle="round",
                solid_joinstyle="round")
        ax.set_aspect("equal")
        ax.set_title(name.upper(), fontsize=12, weight="bold")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        pad = 1.0
        ax.set_xlim(min(xs) - pad, max(xs) + pad)
        ax.set_ylim(min(ys) - pad, max(ys) + pad)

    fig.suptitle("Thumbnail squint test — can you tell what each one is?",
                 fontsize=14)
    out_path = out_dir / "all_shapes_thumbnails.png"
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="../shape_previews")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, points in SHAPES.items():
        path = render_shape(name, points, out_dir)
        print(f"  {name:8s}  {len(points) - 1} anchors  →  {path}")

    thumb_path = render_thumbnail_grid(out_dir)
    print(f"  thumbnails →  {thumb_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
