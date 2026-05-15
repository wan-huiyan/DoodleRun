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

from stravart.crossref import NominatimStreetClient
from stravart.gpx_export import GpxMetadata
from stravart.reconstruct import reconstruct

# RANSAC inside fit_affine uses numpy.random; seed both numpy and python
# random so the projected polyline is byte-identical across sweep cells.
import numpy as np
import random
np.random.seed(42)
random.seed(42)


SWEEPS = [
    # (waypoint_step_m, k_shortest_paths, rerank, label)
    (30.0, 1, "shape", "baseline (Phase 4a defaults)"),
    (15.0, 1, "shape", "Option 1 only (denser waypoints)"),
    (30.0, 3, "shape", "Option 2 only (k=3 shape rerank)"),
    (15.0, 3, "shape", "Options 1+2 (current Phase 4b default)"),
    (50.0, 5, "shape", "sparser + larger K (rerank-heavy)"),
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

    results = []
    for step, k, rerank, label in SWEEPS:
        print(f"\n=== {label} (step={step}, k={k}, rerank={rerank}) ===")
        # Re-seed per cell so each run uses the same RANSAC sample order
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
            min_confidence=0.0,    # we want every result, even low-conf
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
            "elapsed_s": round(elapsed, 1),
            "waypoints": m.waypoints_used if m else 0,
            "reranked": m.reranked_segments if m else 0,
            "snap_points": len(m.coords) if m else 0,
            "snap_length_m": round(m.length_m, 0) if m else 0,
            "fidelity": round(f.score, 3) if f else None,
            "frechet_m": round(f.frechet_m, 0) if f else None,
            "buffered_iou": round(f.buffered_iou, 3) if f else None,
            "confidence": round(rec.confidence, 3),
        }
        results.append(out)
        print(json.dumps(out, indent=2))

    out_path = ROOT / f"stravart/data/phase4b_diag/sweep_{rid:05d}.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_path.relative_to(ROOT)}")

    # Compact comparison table
    print("\n--- comparison ---")
    print(f"{'label':<42} {'step':>4} {'k':>2} {'wp':>4} {'rerank':>6} {'frechet':>8} {'fidelity':>8} {'iou':>5}")
    for r in results:
        print(f"{r['label']:<42} {r['step_m']:>4.0f} {r['k']:>2} {r['waypoints']:>4} "
              f"{r['reranked']:>6} {r['frechet_m'] or 0:>8.0f} {r['fidelity']:>8} {r['buffered_iou']:>5}")


if __name__ == "__main__":
    main()
