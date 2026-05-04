"""Diagnose why strav.art route extraction is losing the body+legs structure.

For each input image we render a 5-panel diagnostic:
  panel 1: source image (fitted to canvas, gray subdued)
  panel 2: ALL non-background pixels colored, to reveal what palette is actually
           used (red? pink? magenta? blue? green?). Shows the HSV histogram of
           the candidate-line pixels for color tuning.
  panel 3: current pipeline result — old red-mask + close + RETR_EXTERNAL
           outermost contour, drawn over the source.
  panel 4: NEW pipeline candidate — wide red/magenta mask + skeletonize, drawn
           over the source (this preserves leg loops).
  panel 5: route polyline reconstructed from the skeleton via graph traversal,
           rendered standalone on white. This is what would become the template.

The current bug hypothesis: cv2.findContours with RETR_EXTERNAL on a
DILATED line mask returns the OUTER ENVELOPE of the line, which is the
silhouette of the route's "convex shell" — interior leg loops (which are
HOLES in the mask, not outer features) get lost. Skeletonization preserves
the entire line including each leg loop because it walks the line itself,
not its envelope.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from skimage.morphology import skeletonize


def red_mask_old(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, (0,   90, 60),  (12,  255, 255))
    m2 = cv2.inRange(hsv, (160, 90, 60),  (179, 255, 255))
    return cv2.bitwise_or(m1, m2)


def red_mask_wide(bgr: np.ndarray) -> np.ndarray:
    """Wider mask covering: red, deep pink, magenta, dark red, salmon."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, (0,   60, 50),  (15,  255, 255))   # red->orange-red
    m2 = cv2.inRange(hsv, (155, 60, 50),  (179, 255, 255))   # deep pink->red
    m3 = cv2.inRange(hsv, (140, 80, 50),  (170, 255, 255))   # magenta
    return cv2.bitwise_or(cv2.bitwise_or(m1, m2), m3)


def old_contour(bgr: np.ndarray):
    mask = red_mask_old(bgr)
    H, W = bgr.shape[:2]
    k = max(3, int(min(H, W) / 200) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    closed = cv2.dilate(closed, kernel, iterations=1)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    cnt = max(contours, key=cv2.contourArea)
    return cnt[:, 0, :]


def skeleton_polyline(bgr: np.ndarray):
    """Return a list of polylines (one per skeleton connected component)."""
    mask = red_mask_wide(bgr)
    H, W = bgr.shape[:2]
    k = max(3, int(min(H, W) / 250) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    skel = skeletonize(closed > 0).astype(np.uint8) * 255
    # For visualization: dilate the skeleton 1 px so it shows up.
    skel_show = cv2.dilate(skel, np.ones((2, 2), np.uint8), iterations=1)
    # Decompose into connected components, return their pixel coords.
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(skel)
    polylines = []
    for lab in range(1, n_labels):
        if stats[lab, cv2.CC_STAT_AREA] < 30:
            continue
        ys, xs = np.where(labels == lab)
        polylines.append(np.column_stack([xs, ys]))
    return skel_show, polylines


def render_panel(ax, img, title):
    if img.ndim == 2:
        ax.imshow(img, cmap="gray")
    else:
        ax.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    ax.set_title(title, fontsize=9)
    ax.set_xticks([]); ax.set_yticks([])


def diagnose(img_path: Path, out_path: Path):
    bgr = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    if bgr is None:
        print(f"  ! decode failed: {img_path}")
        return
    H, W = bgr.shape[:2]

    # Panel 2: just the wide red mask.
    wide = red_mask_wide(bgr)

    # Panel 3: old contour overlay.
    cnt = old_contour(bgr)
    overlay_old = bgr.copy()
    if cnt is not None:
        cv2.polylines(overlay_old, [cnt.reshape(-1, 1, 2).astype(np.int32)],
                      isClosed=True, color=(0, 255, 0), thickness=3)

    # Panel 4: skeleton overlay + skeleton points.
    skel_show, polylines = skeleton_polyline(bgr)
    overlay_skel = bgr.copy()
    overlay_skel[skel_show > 0] = (0, 255, 0)

    # Panel 5: skeleton points drawn standalone on white.
    canvas = np.full_like(bgr, 255)
    for pl in polylines:
        for p in pl:
            cv2.circle(canvas, (int(p[0]), int(p[1])), 1, (0, 0, 0), -1)

    fig, axes = plt.subplots(1, 5, figsize=(22, 4.5))
    render_panel(axes[0], bgr, f"source\n{img_path.name}")
    render_panel(axes[1], wide, "wide red+magenta mask")
    render_panel(axes[2], overlay_old, "OLD: largest external contour")
    render_panel(axes[3], overlay_skel, "NEW: skeletonized line")
    render_panel(axes[4], canvas, "NEW: skeleton points only")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, facecolor="white")
    plt.close(fig)
    print(f"  -> {out_path.name}  (n_components={len(polylines)})")


def main():
    root = Path(__file__).resolve().parent.parent
    raw_dir = root / "data" / "strav_raw" / "elephant"
    out_dir = root / "diagnostics" / "elephant"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Approved set (by source filename).
    approved_sources = [
        "052_1594135339655-B5TZTG61UGZ7POPHFCLW.jpg",
        "006_1636374243088-1NHR5VXQUZAKUQ1UV0CZ.jpg",
        "028_1612619273909-OZLHJBX24QP1WBVWCTEL.jpg",
        "040_1605872179406-5YAXRVLY4DRN91DAFJEB.jpg",
        "044_1599996648441-6E607HJQPS4MF25VAMRL.jpg",
        "051_1594991930755-X0H1R588VGXK3C8LBUHR.jpg",
        "001_1658852877005-WBSCNLNB19R7PK4CH9C2.jpg",
    ]
    for src in approved_sources:
        p = raw_dir / src
        if not p.exists():
            print(f"missing: {p}")
            continue
        diagnose(p, out_dir / f"diag_{src.replace('.jpg','')}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
