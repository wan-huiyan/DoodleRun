"""Diagnose what the largest-component filter drops on a real route.

Renders: original | HSV mask | all components ≥ min_area | the kept largest
component. Highlights the dropped components in a separate colour so we can
SEE what fraction of the route the current extractor is throwing away.
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

from stravart.contour import clean_mask, route_mask_colored


def diagnose(rid: int, out_dir: Path):
    img_path = ROOT / f"stravart/data/phase4a_poc/per_image/route_{rid:05d}/01_original.jpg"
    img = cv2.imread(str(img_path))

    # Current pipeline
    raw = route_mask_colored(img)
    cleaned_kept = clean_mask(raw, close_kernel=3, min_area=200)
    # Alternate: bigger close kernel to bridge label gaps
    cleaned_kept_big = clean_mask(raw, close_kernel=9, min_area=200)

    # All components ≥ min_area (what we WANT to keep)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    closed = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, k)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    # All components above 200 px area
    significant = []
    if areas.size:
        biggest_idx = int(areas.argmax()) + 1
        for i in range(1, n_labels):
            if stats[i, cv2.CC_STAT_AREA] >= 200:
                significant.append(i)

        # Colour-coded: kept (= biggest) in red, dropped in cyan
        diag = np.zeros((*labels.shape, 3), dtype=np.uint8)
        for i in significant:
            if i == biggest_idx:
                diag[labels == i] = (60, 60, 220)   # BGR red — kept
            else:
                diag[labels == i] = (220, 200, 60)  # BGR cyan — dropped
    else:
        diag = np.zeros_like(img)

    print(f"\n[#{rid:05d}] components ≥ 200px area: {len(significant)}")
    if significant:
        print(f"   largest: {areas.max()} px  (currently the ONLY one kept)")
        for i in significant:
            area = stats[i, cv2.CC_STAT_AREA]
            if i != biggest_idx:
                print(f"   DROPPED: component {i}, area={area} px ({area/areas.max()*100:.0f}% of biggest)")

    # Also try big-close-kernel approach for comparison
    n_lab_big, _, stats_big, _ = cv2.connectedComponentsWithStats(
        cv2.morphologyEx(raw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))),
        connectivity=8,
    )
    big_areas = stats_big[1:, cv2.CC_STAT_AREA]
    significant_big = (big_areas >= 200).sum() if big_areas.size else 0
    print(f"   with close_kernel=9: {significant_big} components ≥ 200px area "
          f"(largest = {big_areas.max() if big_areas.size else 0} px)")

    # Compose 4-panel
    fig, axes = plt.subplots(1, 4, figsize=(18, 5))
    fig.suptitle(f"#{rid:05d} contour extraction diagnostic", fontsize=11)

    axes[0].imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    axes[0].set_title("original")
    axes[0].axis("off")

    axes[1].imshow(raw, cmap="gray")
    axes[1].set_title("HSV warm-colour mask (raw)")
    axes[1].axis("off")

    axes[2].imshow(cv2.cvtColor(diag, cv2.COLOR_BGR2RGB))
    axes[2].set_title(
        f"close=3px: components ≥ 200px\n"
        f"red = kept (current); cyan = DROPPED ({len(significant)-1} pieces)"
    )
    axes[2].axis("off")

    axes[3].imshow(cleaned_kept_big, cmap="gray")
    axes[3].set_title(f"close=9px + keep-largest\n(broader bridging)")
    axes[3].axis("off")

    plt.tight_layout()
    out = out_dir / f"contour_diag_{rid:05d}.png"
    plt.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"   wrote {out.relative_to(ROOT)}")


def main():
    rids = [int(x) for x in sys.argv[1:]] or [5, 208, 800, 1135, 584]
    out_dir = ROOT / "stravart/data/phase4b_diag"
    out_dir.mkdir(parents=True, exist_ok=True)
    for rid in rids:
        diagnose(rid, out_dir)


if __name__ == "__main__":
    main()
