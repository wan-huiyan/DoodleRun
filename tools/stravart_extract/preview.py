"""Render numbered preview grids of extracted templates for human voting.

Each grid shows N template thumbnails, each labelled with a 1-based index
(unique within the grid) plus the source filename suffix so votes can be
traced back to the underlying JSON.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def render_grid(
    json_paths: list[Path],
    out_path: Path,
    cols: int = 6,
    cell_in: float = 2.4,
    title: str = "",
) -> None:
    n = len(json_paths)
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(
        rows, cols,
        figsize=(cols * cell_in, rows * cell_in + 0.4),
        squeeze=False,
    )
    for ax in axes.flat:
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlim(-0.05, 1.05)
        ax.set_ylim(-0.05, 1.05)
        ax.set_aspect("equal")
        ax.set_facecolor("#f7f7f7")
    for idx, jp in enumerate(json_paths):
        r, c = divmod(idx, cols)
        ax = axes[r][c]
        data = json.loads(jp.read_text())
        pts = np.array(data["points"])
        ax.plot(pts[:, 0], pts[:, 1], color="#c1272d", linewidth=1.6)
        ax.fill(pts[:, 0], pts[:, 1], color="#c1272d", alpha=0.10)
        label = f"{idx + 1:02d}  {jp.stem[:18]}"
        ax.set_title(label, fontsize=8, loc="left", pad=2)
    # Blank out unused cells.
    for blank in range(n, rows * cols):
        r, c = divmod(blank, cols)
        axes[r][c].set_visible(False)
    if title:
        fig.suptitle(title, fontsize=12, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.985 if title else 1.0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--templates", type=Path, default=Path("templates_stravart"))
    ap.add_argument("--out", type=Path, default=Path("previews"))
    ap.add_argument("--per-grid", type=int, default=24)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--limit-per-cat", type=int, default=None,
                    help="Cap how many templates we render per category total.")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    cats = sorted(p for p in args.templates.iterdir() if p.is_dir())
    index_lines = ["# strav.art template previews\n"]
    for cat_dir in cats:
        jsons = sorted(cat_dir.glob("*.json"))
        if not jsons:
            continue
        if args.limit_per_cat:
            jsons = jsons[: args.limit_per_cat]
        per = args.per_grid
        total_grids = math.ceil(len(jsons) / per)
        for g in range(total_grids):
            chunk = jsons[g * per:(g + 1) * per]
            out_path = args.out / f"{cat_dir.name}_grid_{g + 1:02d}.png"
            title = f"{cat_dir.name}  —  grid {g + 1}/{total_grids}  ({len(chunk)} templates, indices 1–{len(chunk)})"
            render_grid(chunk, out_path, cols=args.cols, title=title)
            print(f"wrote {out_path}")
            index_lines.append(f"- `{out_path.name}` — {len(chunk)} templates from `{cat_dir.name}`")
    (args.out / "INDEX.md").write_text("\n".join(index_lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
