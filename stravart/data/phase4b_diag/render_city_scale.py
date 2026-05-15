"""Render Phase 4b city-scale fallback diagnostics for the OCR0 routes.

Offline: uses the locally-cached 01_original.jpg per route, runs the
contour extractor + centroid_project module, plots the result on a
simple lat/lon panel. No Nominatim, OSMnx, or EasyOCR involved.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Make stravart importable when invoked as a script
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from stravart.centroid_project import centroid_project_contour
from stravart.contour import extract_route


OCR0_ROUTES = [5, 208, 800, 1135, 1359]    # Manchester Dog, Berlin Mutt, Munich Lion, Rotterdam Turtles, Amsterdam Ajax


def load_image(rid: int) -> np.ndarray | None:
    p = ROOT / f"stravart/data/phase4a_poc/per_image/route_{rid:05d}/01_original.jpg"
    if not p.exists():
        return None
    return cv2.imread(str(p))


def get_title_latlon(rid: int) -> tuple[float, float, str, float] | None:
    conn = sqlite3.connect(str(ROOT / "stravart/data/stravart.sqlite"))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT title, lat, lon, geocode_confidence FROM routes WHERE id=?", (rid,)
    ).fetchone()
    conn.close()
    if row is None or row["lat"] is None:
        return None
    return row["lat"], row["lon"], row["title"], row["geocode_confidence"]


def render_one(rid: int, out_dir: Path) -> dict | None:
    img = load_image(rid)
    if img is None:
        print(f"  [{rid}] no cached image; skipping")
        return None
    info = get_title_latlon(rid)
    if info is None:
        print(f"  [{rid}] no title lat/lon; skipping")
        return None
    lat, lon, title, conf = info

    contour = extract_route(img)
    if not contour.polyline or len(contour.polyline) < 10:
        print(f"  [{rid}] no contour")
        return None

    proj = centroid_project_contour(
        contour.polyline,
        city_lat=lat, city_lon=lon,
        target_width_m=4000.0,
    )

    # 3-panel diagnostic: original | extracted contour overlay | geographic placement
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle(
        f"#{rid:05d}  {title[:50]}    Phase 4b city-scale (decorative)\n"
        f"city centroid: ({lat:.4f}, {lon:.4f})    "
        f"bbox: {proj.bbox_width_m:.0f}m × {proj.bbox_height_m:.0f}m    "
        f"scale: {proj.scale_m_per_pixel:.2f} m/px",
        fontsize=10,
    )

    # panel 1: original
    axes[0].imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    axes[0].set_title("original (basemap shows place names, not streets)")
    axes[0].axis("off")

    # panel 2: contour on top of grey image
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    axes[1].imshow(grey, cmap="gray", alpha=0.5)
    xs, ys = zip(*contour.polyline)
    axes[1].plot(xs, ys, "r-", linewidth=1.5)
    axes[1].set_title(f"extracted contour ({len(contour.polyline)} points)")
    axes[1].set_xlim(0, img.shape[1])
    axes[1].set_ylim(img.shape[0], 0)
    axes[1].axis("off")

    # panel 3: geographic placement (lat/lon)
    plats, plons = zip(*proj.polyline)
    axes[2].plot(plons, plats, "g-", linewidth=1.2, label="contour projected at city scale")
    axes[2].plot(lon, lat, "k*", markersize=14, label=f"city centroid")
    axes[2].set_xlabel("longitude (°E)")
    axes[2].set_ylabel("latitude (°N)")
    axes[2].set_aspect("equal", adjustable="datalim")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc="upper right", fontsize=8)
    axes[2].set_title("city-scale placement (decorative card, not navigable)")

    plt.tight_layout()
    out_path = out_dir / f"city_scale_{rid:05d}.png"
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)

    return {
        "rid": rid, "title": title,
        "city_lat": lat, "city_lon": lon,
        "n_polyline": len(proj.polyline),
        "bbox_width_m": proj.bbox_width_m,
        "bbox_height_m": proj.bbox_height_m,
        "scale_m_per_px": proj.scale_m_per_pixel,
        "out": str(out_path.relative_to(ROOT)),
    }


def main():
    out_dir = ROOT / "stravart/data/phase4b_diag"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for rid in OCR0_ROUTES:
        print(f"rendering route {rid}...")
        r = render_one(rid, out_dir)
        if r is not None:
            results.append(r)
    (out_dir / "city_scale_summary.json").write_text(json.dumps(results, indent=2))
    print(f"\nWrote {len(results)} city-scale diagnostics to {out_dir.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
