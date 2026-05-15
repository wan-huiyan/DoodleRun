"""Visualise what's lost in trace_route.

For each route: render
  panel 1: cleaned mask
  panel 2: skeleton (every pixel that the trace SHOULD reach)
  panel 3: current trace_route output (one polyline, longest path)
  panel 4: skeleton pixels NOT in the trace (red = lost)

The bigger the red area, the more route the current extractor is dropping.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from stravart.contour import clean_mask, route_mask_colored, skeleton_of, trace_route


def diagnose(rid: int, out_dir: Path):
    img_path = ROOT / f"stravart/data/phase4a_poc/per_image/route_{rid:05d}/01_original.jpg"
    img = cv2.imread(str(img_path))
    raw = route_mask_colored(img)
    cleaned = clean_mask(raw, close_kernel=3)
    skel = skeleton_of(cleaned)
    poly = trace_route(skel)

    skel_pixel_count = int(skel.sum())
    traced_pixel_count = len(poly)
    coverage = traced_pixel_count / max(skel_pixel_count, 1) * 100
    lost = skel_pixel_count - traced_pixel_count

    # Build "lost pixels" mask
    traced_mask = np.zeros_like(skel)
    for x, y in poly:
        if 0 <= y < traced_mask.shape[0] and 0 <= x < traced_mask.shape[1]:
            traced_mask[y, x] = 1
    lost_mask = (skel == 1) & (traced_mask == 0)

    print(f"\n[#{rid:05d}]")
    print(f"   skeleton pixels:      {skel_pixel_count}")
    print(f"   traced pixels:        {traced_pixel_count}")
    print(f"   coverage:             {coverage:.1f}%")
    print(f"   LOST pixels:          {lost}")

    fig, axes = plt.subplots(1, 4, figsize=(20, 5))
    fig.suptitle(
        f"#{rid:05d}  trace_route coverage = {coverage:.1f}%   "
        f"(skeleton={skel_pixel_count} px, traced={traced_pixel_count}, LOST={lost})",
        fontsize=10,
    )

    axes[0].imshow(cleaned, cmap="gray")
    axes[0].set_title("cleaned mask")
    axes[0].axis("off")

    axes[1].imshow(skel, cmap="gray")
    axes[1].set_title("skeleton (all pixels that SHOULD be traced)")
    axes[1].axis("off")

    overlay = np.zeros((*skel.shape, 3), dtype=np.uint8)
    if poly:
        xs, ys = zip(*poly)
        for x, y in poly:
            if 0 <= y < overlay.shape[0] and 0 <= x < overlay.shape[1]:
                overlay[y, x] = (0, 255, 0)   # green = traced
    axes[2].imshow(overlay)
    axes[2].set_title(f"current trace_route polyline\n({len(poly)} points)")
    axes[2].axis("off")

    # Red: lost; green: traced
    diff = np.zeros((*skel.shape, 3), dtype=np.uint8)
    diff[traced_mask == 1] = (0, 200, 0)
    diff[lost_mask] = (255, 60, 60)
    axes[3].imshow(diff)
    axes[3].set_title(
        f"green = traced, RED = LOST ({lost} skel px, {lost/max(skel_pixel_count,1)*100:.0f}%)"
    )
    axes[3].axis("off")

    plt.tight_layout()
    out = out_dir / f"skeleton_diag_{rid:05d}.png"
    plt.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"   wrote {out.relative_to(ROOT)}")


def main():
    rids = [int(x) for x in sys.argv[1:]] or [5, 208, 800, 1135, 584, 910]
    out_dir = ROOT / "stravart/data/phase4b_diag"
    out_dir.mkdir(parents=True, exist_ok=True)
    for rid in rids:
        diagnose(rid, out_dir)


if __name__ == "__main__":
    main()
