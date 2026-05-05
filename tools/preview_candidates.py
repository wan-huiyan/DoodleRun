"""Render preview PNG grids for every shape candidate.

Outputs (under `samples/previews/v6/`):
- One PNG per family (`pig.png`, `cat.png`, …) — 5-up grid showing
  candidates 1-5 side by side.
- `all_candidates.png` — master 5×5 grid (rows = families, cols = candidates).

Each candidate is rendered three ways within a single tile:
- Outline as a thick blue line (the silhouette).
- Interior features as red lines (whiskers / nostrils / eyes / etc).
- Start point as a green dot.

The composed route (outline + detours) is what the runner actually traces;
showing outline + features separately makes it easy to judge whether the
interior detail matches the silhouette intent.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

PROTO = Path(__file__).resolve().parent.parent / "prototype"
sys.path.insert(0, str(PROTO))

from shapes import SHAPES_FULL  # noqa: E402
from shape_utils import bounding_box  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "samples" / "previews" / "v6"


FAMILY_ORDER = ["pig", "cat", "dog", "dino", "chicken"]


def _draw_tile(ax, shape) -> None:
    xs = [p[0] for p in shape.outline]
    ys = [p[1] for p in shape.outline]
    ax.plot(xs, ys, color="#1a73e8", linewidth=2.5,
            solid_joinstyle="round", solid_capstyle="round")
    for feat in shape.interior_features:
        if not feat:
            continue
        fx = [p[0] for p in feat]
        fy = [p[1] for p in feat]
        ax.plot(fx, fy, color="#d93025", linewidth=1.6,
                solid_joinstyle="round", solid_capstyle="round")
        # Mark endpoints so single-point or two-point features (whiskers)
        # are visible even when collinear with the line.
        ax.plot(fx, fy, "o", color="#d93025", markersize=2.5)
    ax.plot(xs[0], ys[0], "o", color="#137333", markersize=6,
            markeredgecolor="white", markeredgewidth=1.0, zorder=5)
    ax.set_aspect("equal")
    ax.axis("off")
    min_x, min_y, max_x, max_y = bounding_box(shape.outline)
    pad = max(max_x - min_x, max_y - min_y) * 0.08
    ax.set_xlim(min_x - pad, max_x + pad)
    ax.set_ylim(min_y - pad, max_y + pad)
    label = shape.name.split("_candidate_")[-1] if "_candidate_" in shape.name else "1*"
    desc = shape.metadata.get("description", "")
    title = f"#{label}"
    if desc:
        title += f" — {desc[:48]}"
    ax.set_title(title, fontsize=9, pad=4)


def _candidates_for(family: str):
    """Return [(label, shape)] in candidate-number order, padded to 5."""
    by_label = {}
    for name, shape in SHAPES_FULL.items():
        if shape.family != family:
            continue
        if "_candidate_" in name:
            label = int(name.split("_candidate_")[-1])
            by_label[label] = shape
        elif name == family:
            by_label.setdefault(1, shape)  # canonical = candidate 1
    return [(i, by_label.get(i)) for i in range(1, 6)]


def render_family_grid(family: str) -> Path:
    candidates = _candidates_for(family)
    fig, axes = plt.subplots(1, 5, figsize=(20, 5), dpi=140)
    fig.suptitle(f"{family} — 5 candidates", fontsize=14, y=0.98)
    for ax, (label, shape) in zip(axes, candidates):
        if shape is None:
            ax.text(0.5, 0.5, f"#{label}\n(missing)", ha="center", va="center",
                    transform=ax.transAxes, fontsize=12, color="#888")
            ax.axis("off")
            continue
        _draw_tile(ax, shape)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{family}.png"
    fig.savefig(out, bbox_inches="tight", facecolor="white", pad_inches=0.2)
    plt.close(fig)
    return out


def render_master_grid() -> Path:
    fig, axes = plt.subplots(len(FAMILY_ORDER), 5,
                             figsize=(20, 4 * len(FAMILY_ORDER)), dpi=130)
    for row, family in enumerate(FAMILY_ORDER):
        candidates = _candidates_for(family)
        for col, (label, shape) in enumerate(candidates):
            ax = axes[row][col]
            if col == 0:
                ax.set_ylabel(family, fontsize=14, rotation=0,
                              labelpad=40, va="center")
            if shape is None:
                ax.text(0.5, 0.5, f"#{label}\n(missing)", ha="center",
                        va="center", transform=ax.transAxes,
                        fontsize=12, color="#888")
                ax.axis("off")
                continue
            _draw_tile(ax, shape)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "all_candidates.png"
    fig.suptitle("DoodleRun shape candidates v6 — outline (blue) + interior features (red)",
                 fontsize=15, y=0.995)
    fig.savefig(out, bbox_inches="tight", facecolor="white", pad_inches=0.3)
    plt.close(fig)
    return out


def main() -> None:
    for family in FAMILY_ORDER:
        path = render_family_grid(family)
        print(f"wrote {path.relative_to(Path(__file__).resolve().parent.parent)}")
    master = render_master_grid()
    print(f"wrote {master.relative_to(Path(__file__).resolve().parent.parent)}")


if __name__ == "__main__":
    main()
