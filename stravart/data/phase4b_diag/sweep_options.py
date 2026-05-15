"""Parameter sweep for options 1 + 2 on a single route.

Runs the same image through map_match with different (waypoint_step_m,
k_shortest_paths, rerank) combinations and reports fidelity / fréchet /
reranked-segment counts so we can see which combination actually moves
the needle on the Travelling Elephant.

Reuses the OSMnx graph cache so the 4-cell sweep is roughly 1x the
single-run wall-clock plus k-paths overhead.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from stravart.crossref import NominatimStreetClient, PerStreetNodeClient
from stravart.gpx_export import GpxMetadata
from stravart.reconstruct import reconstruct

# RANSAC inside fit_affine uses numpy.random; seed both numpy and python
# random so the projected polyline is byte-identical across sweep cells.
import numpy as np
import random
np.random.seed(42)
random.seed(42)


SWEEPS = [
    # (waypoint_step_m, k_shortest_paths, rerank, use_via_nodes, via_node_selection, label)
    (30.0, 1, "shape", False, "nominatim-centroid", "baseline (Phase 4a defaults, no via)"),
    (15.0, 1, "shape", False, "nominatim-centroid", "Option 1 only (denser waypoints, no via)"),
    (30.0, 3, "shape", False, "nominatim-centroid", "Option 2 only (k=3 shape rerank, no via)"),
    (15.0, 3, "shape", False, "nominatim-centroid", "Options 1+2 (no via)"),
    (30.0, 1, "shape", True,  "nominatim-centroid",
        "Option 4 (Nominatim centroid via — negative-result baseline)"),
    (15.0, 3, "shape", True,  "nominatim-centroid", "Options 1+2+4 (Nominatim centroid)"),
    # Phase 4c B1 — per-street node enumeration via Overpass. Pins each via to
    # the OSM node closest to where the projected cartoon ACTUALLY crosses the
    # named street, not Nominatim's coarse street-centroid.
    (30.0, 1, "shape", True,  "per-street",
        "Phase 4c B1 — Option 4 + per-street via-nodes"),
    (15.0, 3, "shape", True,  "per-street",
        "Phase 4c B1 — Options 1+2+4 + per-street via-nodes"),
]


def main():
    rid = int(sys.argv[1]) if len(sys.argv) > 1 else 584
    import sqlite3
    conn = sqlite3.connect(str(ROOT / "stravart/data/stravart.sqlite"))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT title, image_url, lat, lon, geocode_confidence FROM routes WHERE id=?",
        (rid,),
    ).fetchone()
    conn.close()
    assert row is not None

    client = NominatimStreetClient(
        cache_path=ROOT / "stravart/data/nominatim_cache.json",
    )
    # Phase 4c B1 — shared per-street node cache across all cells so the
    # Overpass round-trips happen once per (street, bbox), not once per cell.
    per_street_client = PerStreetNodeClient(
        cache_path=ROOT / "stravart/data/per_street_node_cache.json",
    )

    results = []
    for step, k, rerank, use_via, via_sel, label in SWEEPS:
        print(f"\n=== {label} (step={step}, k={k}, rerank={rerank}, "
              f"via={use_via}, sel={via_sel}) ===")
        np.random.seed(42)
        random.seed(42)
        t0 = time.time()
        rec = reconstruct(
            row["image_url"],
            crossref_client=client,
            download_graph=True,
            waypoint_step_m=step,
            mapmatch_k_paths=k,
            mapmatch_rerank=rerank,
            mapmatch_use_via_nodes=use_via,
            via_node_selection=via_sel,
            per_street_node_client=per_street_client,
            min_confidence=0.0,
            title_latlon=(row["lat"], row["lon"]),
            title_confidence=row["geocode_confidence"] or 0.5,
        )
        elapsed = time.time() - t0
        m = rec.matched
        f = rec.fidelity
        out = {
            "label": label,
            "step_m": step,
            "k": k,
            "rerank": rerank,
            "use_via_nodes": use_via,
            "via_node_selection": via_sel,
            "elapsed_s": round(elapsed, 1),
            "waypoints": m.waypoints_used if m else 0,
            "reranked": m.reranked_segments if m else 0,
            "via_pinned": m.via_nodes_pinned if m else 0,
            "per_street_hits": rec.diagnostics.get("via_per_street_hits"),
            "per_street_misses": rec.diagnostics.get("via_per_street_misses"),
            "snap_points": len(m.coords) if m else 0,
            "snap_length_m": round(m.length_m, 0) if m else 0,
            "fidelity": round(f.score, 3) if f else None,
            "frechet_m": round(f.frechet_m, 0) if f else None,
            "buffered_iou": round(f.buffered_iou, 3) if f else None,
            "confidence": round(rec.confidence, 3),
        }
        results.append(out)
        print(json.dumps(out, indent=2))

    out_path = ROOT / f"stravart/data/phase4b_diag/sweep_perstreet_{rid:05d}.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_path.relative_to(ROOT)}")

    print("\n--- comparison ---")
    print(f"{'label':<50} {'step':>4} {'k':>2} {'via':>3} {'wp':>4} "
          f"{'rrnk':>4} {'pin':>3} {'frechet':>7} {'fidelity':>8} {'iou':>5}")
    for r in results:
        fid = f"{r['fidelity']:.3f}" if r['fidelity'] is not None else "  —  "
        iou = f"{r['buffered_iou']:.3f}" if r['buffered_iou'] is not None else "  —  "
        print(f"{r['label']:<50} {r['step_m']:>4.0f} {r['k']:>2} "
              f"{'Y' if r['use_via_nodes'] else 'n':>3} "
              f"{r['waypoints']:>4} {r['reranked']:>4} {r['via_pinned']:>3} "
              f"{r['frechet_m'] or 0:>7.0f} {fid:>8} {iou:>5}")


if __name__ == "__main__":
    main()
