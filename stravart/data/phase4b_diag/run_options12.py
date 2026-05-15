"""Re-run a single curated route under Phase 4b options 1+2 and overlay
the snap against the persisted Phase 4a snap for visual A/B.

Targets routes where Phase 4a's snap visibly distorted the cartoon shape
(panel 4 of route_NNNNN_summary.png shows red/blue divergence in places).

Outputs:
    phase4b_diag/route_NNNNN_phase4b.json   — full Reconstruction summary
    phase4b_diag/route_NNNNN_compare.png    — 1x3: original | p4a snap | p4b snap
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from stravart.crossref import NominatimStreetClient
from stravart.gpx_export import GpxMetadata
from stravart.reconstruct import reconstruct


def load_p4a(rid: int) -> dict:
    p = ROOT / f"stravart/data/phase4a_poc/per_image/route_{rid:05d}/reconstruction.json"
    return json.load(open(p)) if p.exists() else {}


def coords_from_reconstruction(rec) -> dict:
    """Pull the polylines we need for the comparison panel."""
    return {
        "projected": rec.geo_polyline or [],
        "snapped":   rec.matched.coords if rec.matched else [],
        "n_gcps": rec.diagnostics.get("n_gcps", 0),
        "rmse_m": rec.georectification.rmse_m if rec.georectification else None,
        "fidelity": rec.fidelity.score if rec.fidelity else None,
        "frechet_m": rec.fidelity.frechet_m if rec.fidelity else None,
        "confidence": rec.confidence,
        "reranked_segments": rec.matched.reranked_segments if rec.matched else 0,
        "waypoints_used": rec.matched.waypoints_used if rec.matched else 0,
    }


def overlay_panel(rid: int, p4a: dict, p4b_coords: dict, out_path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    p4a_fid = (p4a.get("stages", {}) or {}).get("fidelity", {}) or {}
    fig.suptitle(
        f"#{rid:05d}  options 1+2 vs Phase 4a baseline\n"
        f"Phase 4a: fid={p4a_fid.get('score', 0):.3f}  fréchet={p4a_fid.get('frechet_m', 0):.0f}m  conf={p4a.get('confidence', 0):.2f}    "
        f"Phase 4b: fid={p4b_coords['fidelity'] or 0:.3f}  fréchet={p4b_coords['frechet_m'] or 0:.0f}m  conf={p4b_coords['confidence']:.2f}  "
        f"reranked={p4b_coords['reranked_segments']}/{p4b_coords['waypoints_used']-1}",
        fontsize=10,
    )

    # We don't have run #2's saved geo_polyline in our copy, so the left
    # panel shows the projected polyline (which is unchanged across runs)
    # plus the new snap; the right panel shows the same projection plus
    # only the new snap so the reader can compare to the saved run #2
    # summary panel separately.
    ax_left = axes[0]
    proj = p4b_coords["projected"]
    snap = p4b_coords["snapped"]
    if proj:
        plats, plons = zip(*proj)
        ax_left.plot(plons, plats, "b-", linewidth=1.5, alpha=0.7,
                     label="projected contour (cartoon shape)")
    if snap:
        slats, slons = zip(*snap)
        ax_left.plot(slons, slats, "r-", linewidth=1.5, alpha=0.8,
                     label="Phase 4b snap (options 1+2)")
    ax_left.set_xlabel("longitude (°E)")
    ax_left.set_ylabel("latitude (°N)")
    ax_left.set_aspect("equal", adjustable="datalim")
    ax_left.grid(True, alpha=0.3)
    ax_left.legend(loc="lower right", fontsize=9)
    ax_left.set_title("Phase 4b: shape-aware snap")

    # Right panel: just the new snap on its own (clearer view)
    ax_right = axes[1]
    if snap:
        slats, slons = zip(*snap)
        ax_right.plot(slons, slats, "r-", linewidth=1.8)
        ax_right.fill(slons, slats, color="red", alpha=0.08)
    ax_right.set_xlabel("longitude (°E)")
    ax_right.set_ylabel("latitude (°N)")
    ax_right.set_aspect("equal", adjustable="datalim")
    ax_right.grid(True, alpha=0.3)
    ax_right.set_title("Phase 4b snap (shape isolated)")

    plt.tight_layout()
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


def main():
    rids = [int(x) for x in sys.argv[1:]] or [584, 53]
    out_dir = ROOT / "stravart/data/phase4b_diag"
    out_dir.mkdir(parents=True, exist_ok=True)

    client = NominatimStreetClient(
        cache_path=ROOT / "stravart/data/nominatim_cache.json",
    )

    # Pull image_url + title-latlon from DB for each route
    import sqlite3
    conn = sqlite3.connect(str(ROOT / "stravart/data/stravart.sqlite"))
    conn.row_factory = sqlite3.Row

    for rid in rids:
        row = conn.execute(
            "SELECT title, image_url, lat, lon, geocode_confidence FROM routes WHERE id=?",
            (rid,),
        ).fetchone()
        if row is None:
            print(f"[{rid}] no DB row — skipping")
            continue

        print(f"[{rid}] {row['title'][:60]} — running phase 4b...")
        title_latlon = (
            (row["lat"], row["lon"])
            if row["lat"] is not None and row["lon"] is not None else None
        )
        t0 = time.time()
        rec = reconstruct(
            row["image_url"],
            crossref_client=client,
            download_graph=True,
            title_latlon=title_latlon,
            title_confidence=row["geocode_confidence"] or 0.5,
            gpx_metadata=GpxMetadata(
                name=row["title"][:120],
                description=f"Phase 4b options 1+2 (route {rid})",
            ),
        )
        elapsed = time.time() - t0
        print(f"   conf={rec.confidence:.3f}  fail={rec.failure!s}  elapsed={elapsed:.1f}s  reranked={rec.matched.reranked_segments if rec.matched else '-'}")

        p4b = coords_from_reconstruction(rec)
        # Persist a JSON summary
        (out_dir / f"route_{rid:05d}_phase4b.json").write_text(
            json.dumps({
                "rid": rid,
                "title": row["title"],
                "elapsed_s": elapsed,
                **{k: v for k, v in p4b.items() if k not in ("projected", "snapped")},
                "n_projected_pts": len(p4b["projected"]),
                "n_snapped_pts": len(p4b["snapped"]),
            }, indent=2, default=str),
        )
        p4a = load_p4a(rid)
        overlay_panel(rid, p4a, p4b, out_dir / f"route_{rid:05d}_compare.png")

    conn.close()
    print(f"\nWrote diagnostics to {out_dir.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
