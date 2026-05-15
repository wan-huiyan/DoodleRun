"""Phase 4c Stream A — diagnostic: render projected-polyline vs HMM-snapped
trace vs Dijkstra-snapped trace, plus OSM walking network in the background.

Purpose: the advisor pointed out that if the cartoon's affine projection lands
on the wrong streets to begin with, NO map matcher (HMM, Valhalla, anything)
can fix it. Before declaring HMM a partial win or negative result, plot the
three layers so we can see WHICH layer is wrong.

Run::

    python3 stravart/data/phase4b_diag/diagnose_hmm.py 584
    python3 stravart/data/phase4b_diag/diagnose_hmm.py 53
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
import numpy as np
import random
np.random.seed(42)
random.seed(42)

from stravart.crossref import NominatimStreetClient
from stravart.reconstruct import reconstruct
from stravart.georef import bbox_of_geocoords
from stravart.mapmatch import load_graph


def _route(rid: int, mode: str, sigma: float = 50.0):
    import sqlite3
    conn = sqlite3.connect(str(ROOT / "stravart/data/stravart.sqlite"))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT title, image_url, lat, lon, geocode_confidence FROM routes WHERE id=?",
        (rid,),
    ).fetchone()
    conn.close()
    client = NominatimStreetClient(
        cache_path=ROOT / "stravart/data/nominatim_cache.json",
    )
    np.random.seed(42)
    random.seed(42)
    rec = reconstruct(
        row["image_url"],
        crossref_client=client,
        download_graph=True,
        waypoint_step_m=30.0,
        mapmatch_mode=mode,
        hmm_obs_noise_m=sigma,
        min_confidence=0.0,
        title_latlon=(row["lat"], row["lon"]),
        title_confidence=row["geocode_confidence"] or 0.5,
    )
    return row, rec


def main():
    rid = int(sys.argv[1]) if len(sys.argv) > 1 else 584
    print(f"diagnose_hmm for route {rid}")

    row, rec_d = _route(rid, "dijkstra")
    print(f"  dijkstra fidelity={rec_d.fidelity.score:.3f} frechet={rec_d.fidelity.frechet_m:.0f}m")
    _, rec_h = _route(rid, "hmm", sigma=50.0)
    print(f"  hmm σ=50    fidelity={rec_h.fidelity.score:.3f} frechet={rec_h.fidelity.frechet_m:.0f}m")

    # Reuse rec_d's projected polyline (identical to rec_h's by seed pinning)
    geo = rec_d.geo_polyline
    bbox = bbox_of_geocoords(geo, pad_m=200.0)
    south, north, west, east = bbox

    graph = load_graph(bbox, network_type="walk")

    fig, ax = plt.subplots(figsize=(14, 10))
    # 1. OSM streets in light grey
    for u, v in graph.edges():
        ulat, ulon = graph.nodes[u]["y"], graph.nodes[u]["x"]
        vlat, vlon = graph.nodes[v]["y"], graph.nodes[v]["x"]
        ax.plot([ulon, vlon], [ulat, vlat], color="#cccccc", linewidth=0.6, zorder=1)

    # 2. Projected polyline (the input to map_match)
    lats = [c[0] for c in geo]
    lons = [c[1] for c in geo]
    ax.plot(lons, lats, color="#1f77b4", linewidth=1.4, label="projected polyline (input)", zorder=2)

    # 3. Dijkstra-snapped
    d_lats = [c[0] for c in rec_d.matched.coords]
    d_lons = [c[1] for c in rec_d.matched.coords]
    ax.plot(d_lons, d_lats, color="#d62728", linewidth=1.8,
            label=f"Dijkstra snap (fid={rec_d.fidelity.score:.3f})", alpha=0.7, zorder=3)

    # 4. HMM-snapped
    h_lats = [c[0] for c in rec_h.matched.coords]
    h_lons = [c[1] for c in rec_h.matched.coords]
    ax.plot(h_lons, h_lats, color="#2ca02c", linewidth=1.8,
            label=f"HMM snap σ=50 (fid={rec_h.fidelity.score:.3f})", alpha=0.7, zorder=4)

    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect("equal")
    ax.set_title(f"#{rid:05d} {row['title']!r} — projected polyline vs HMM/Dijkstra snap vs OSM streets\n"
                 f"(If the BLUE polyline already wanders off the grey streets, "
                 f"the error is in the AFFINE PROJECTION, not the map matcher)")
    ax.legend(loc="lower right")

    out_path = ROOT / f"stravart/data/phase4b_diag/diagnose_hmm_{rid:05d}.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=110)
    print(f"  wrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
