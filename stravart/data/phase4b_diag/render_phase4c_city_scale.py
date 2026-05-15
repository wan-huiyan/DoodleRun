"""Render Phase 4c city-scale fallback diagnostics for routes newly promoted
by C1 (low-anchor / low-RMSE + title centroid → city-scale).

Mirrors ``render_city_scale.py`` but targets the routes that Phase 4b would
have hard-failed at the ``min_gcps`` or ``min_rmse`` gate. The diagnostic
panels (original / extracted contour / geographic placement) confirm the
fall-through path produces a sensible decorative output for each.

Offline: no Nominatim / OSMnx — the C1 fall-through doesn't need them once
the OCR street count is low. We project the cartoon at the title centroid
exactly the way the orchestrator would.
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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from stravart.centroid_project import centroid_project_contour
from stravart.contour import extract_route
from stravart.reconstruct import _polylines_total_distance_m


# Curated-20 routes promoted by C1: previously FAIL min_gcps or FAIL conf
# (degenerate fit), now CITY-SCALE thanks to the new fall-through. The 3
# rows below all carry a Phase 1 title centroid in the DB; the other 2
# spec candidates (#60 Hampstead, #1294 Whale-in-Wales) have lat=None
# in the persisted catalog so they remain hard failures until Phase 1
# geocodes them.
PROMOTED_ROUTES = [
    577,    # DUMBO VISITS CAMBRIDGE — was FAIL min_gcps(3<5)
    942,    # LONDON BEAR HALF MARATHON — was FAIL conf 0.31<0.4 (degenerate)
    1272,   # ST ALBANS SHARK — was FAIL min_gcps(4<5)
]


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
        print(f"  [{rid}] no title lat/lon; skipping (still hard-fail under C1)")
        return None
    lat, lon, title, conf = info

    contour = extract_route(img)
    if not contour.polyline or len(contour.polyline) < 10:
        print(f"  [{rid}] no contour")
        return None

    source = contour.polylines if contour.polylines else contour.polyline
    proj = centroid_project_contour(
        source,
        city_lat=lat, city_lon=lon,
        target_width_m=4000.0,
    )
    print(f"  [{rid}] segments={len(contour.polylines)}  "
          f"coverage={contour.skeleton_coverage:.1%}  total={sum(len(p) for p in contour.polylines)} pts")

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle(
        f"#{rid:05d}  {title[:50]}    Phase 4c PROMOTED (C1 fall-through)\n"
        f"city centroid: ({lat:.4f}, {lon:.4f})    "
        f"bbox: {proj.bbox_width_m:.0f}m × {proj.bbox_height_m:.0f}m    "
        f"scale: {proj.scale_m_per_pixel:.2f} m/px",
        fontsize=10,
    )

    axes[0].imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    axes[0].set_title("original (Phase 4b → FAIL · Phase 4c → CITY-SCALE)")
    axes[0].axis("off")

    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    axes[1].imshow(grey, cmap="gray", alpha=0.4)
    total_pts = 0
    for seg in contour.polylines:
        if len(seg) < 2:
            continue
        xs, ys = zip(*seg)
        axes[1].plot(xs, ys, linewidth=1.5, alpha=0.9)
        total_pts += len(seg)
    axes[1].set_title(
        f"extracted contour: {len(contour.polylines)} segments, {total_pts} pts"
    )
    axes[1].set_xlim(0, img.shape[1])
    axes[1].set_ylim(img.shape[0], 0)
    axes[1].axis("off")

    for seg in proj.polylines:
        if len(seg) < 2:
            continue
        slats, slons = zip(*seg)
        axes[2].plot(slons, slats, linewidth=1.2, alpha=0.9)
    axes[2].plot(lon, lat, "k*", markersize=14, label="city centroid")
    axes[2].set_xlabel("longitude (°E)")
    axes[2].set_ylabel("latitude (°N)")
    axes[2].set_aspect("equal", adjustable="datalim")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc="upper right", fontsize=8)
    axes[2].set_title("city-scale placement (decorative, not navigable)")

    plt.tight_layout()
    out_path = out_dir / f"city_scale_phase4c_{rid:05d}.png"
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)

    distance_m = _polylines_total_distance_m(proj.polylines)
    return {
        "rid": rid, "title": title,
        "city_lat": lat, "city_lon": lon,
        "n_polyline": len(proj.polyline),
        "n_segments": len(proj.polylines),
        "bbox_width_m": proj.bbox_width_m,
        "bbox_height_m": proj.bbox_height_m,
        "scale_m_per_px": proj.scale_m_per_pixel,
        "total_distance_m": distance_m,
        "out": str(out_path.relative_to(ROOT)),
    }


def main():
    out_dir = ROOT / "stravart/data/phase4b_diag"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for rid in PROMOTED_ROUTES:
        print(f"rendering route {rid}...")
        r = render_one(rid, out_dir)
        if r is not None:
            results.append(r)
    (out_dir / "city_scale_phase4c_summary.json").write_text(json.dumps(results, indent=2))
    print(f"\nWrote {len(results)} Phase 4c-promoted city-scale diagnostics")


if __name__ == "__main__":
    main()
