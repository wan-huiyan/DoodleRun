"""Build a contact sheet of existing candidate PNGs for visual cherry-picking.

Reads existing per-rank PNGs (rendered by preview.py with FULL template polyline
as the grey reference) and arranges them in a grid with title showing key params.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.image import imread


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suffix", default="_q07_wp64")
    ap.add_argument("--location", default="st_albans")
    ap.add_argument("--animal", default="elephant")
    args = ap.parse_args()

    base = Path("multi_template/previews")
    summary = json.loads(
        (base / f"{args.animal}_{args.location}{args.suffix}_summary.json").read_text()
    )
    cands = summary["top_candidates"]
    n = len(cands)
    cols = 2
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 10, rows * 5.5), dpi=110)
    axes = np.atleast_2d(axes).ravel()
    for ax, c in zip(axes, cands):
        rank = c["rank"]
        vid = c["vote_id"]
        png = base / f"{args.animal}_{args.location}{args.suffix}_top{rank:02d}_{vid}.png"
        if not png.exists():
            ax.set_title(f"r{rank} MISSING", color="red")
            ax.axis("off")
            continue
        # Crop right half (the routed map)
        img = imread(png)
        h, w = img.shape[:2]
        img = img[:, w // 2 :]
        ax.imshow(img)
        ax.axis("off")
        ax.set_title(
            f"#{rank}  {vid}  rot={c['rotation_deg']:+.0f}°  "
            f"scale={c['scale_m']/1000:.1f}km  len={c['route_length_m']/1000:.0f}km    "
            f"iou={c['fidelity']['iou']:.3f}  obj={c['objective']:.3f}",
            fontsize=11,
        )
    for ax in axes[n:]:
        ax.axis("off")
    fig.suptitle(
        f"{args.animal} @ {summary['location_label']}   "
        f"top-{n} candidates (grey = full template polyline, red = routed)",
        fontsize=14,
    )
    out = base / f"_PICK_{args.animal}_{args.location}{args.suffix}.png"
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out, dpi=120, bbox_inches="tight")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
