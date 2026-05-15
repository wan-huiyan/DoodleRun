"""Phase 4c Stream A — single-cell HMM sweep runner (subprocess-friendly).

Runs ONE map-match cell on a chosen route and prints a JSON result to
stdout. Designed to be invoked by ``sweep_hmm.py`` per-cell to guarantee
fresh RNG state per cell (Phase 4b's sweep-options.py had subtle seed
contamination across cells when reconstruct() was called repeatedly in
the same Python process — see lessons.md
``algorithm-sweep-rng-seed-contamination``).

Usage::

    python3 sweep_hmm_cell.py <route_id> <mode> <sigma_m>

``mode`` is "dijkstra" or "hmm"; ``sigma_m`` is the HMM obs-noise σ
(ignored in dijkstra mode but must still be passed). Output is one JSON
blob on stdout suitable for the parent sweep to collect.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
import random
np.random.seed(42)
random.seed(42)

from stravart.crossref import NominatimStreetClient
from stravart.reconstruct import reconstruct


def main():
    rid = int(sys.argv[1])
    mode = sys.argv[2]
    sigma = float(sys.argv[3])

    import sqlite3
    conn = sqlite3.connect(str(ROOT / "stravart/data/stravart.sqlite"))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT title, image_url, lat, lon, geocode_confidence FROM routes WHERE id=?",
        (rid,),
    ).fetchone()
    conn.close()
    assert row is not None, f"route {rid} not in catalog"

    client = NominatimStreetClient(
        cache_path=ROOT / "stravart/data/nominatim_cache.json",
    )

    # Re-seed *immediately before* the call — this is the only place where
    # we hold the RNG state for the reconstruct() call. Subprocess isolation
    # ensures the seed isn't already perturbed by previous cells.
    np.random.seed(42)
    random.seed(42)
    t0 = time.time()
    try:
        rec = reconstruct(
            row["image_url"],
            crossref_client=client,
            download_graph=True,
            waypoint_step_m=30.0,
            mapmatch_mode=mode,
            hmm_obs_noise_m=sigma if sigma > 0 else 50.0,
            min_confidence=0.0,
            title_latlon=(row["lat"], row["lon"]),
            title_confidence=row["geocode_confidence"] or 0.5,
        )
    except Exception as exc:                                       # noqa: BLE001
        out = {
            "route_id": rid, "mode": mode, "sigma_m": sigma,
            "error": repr(exc), "elapsed_s": round(time.time() - t0, 1),
        }
        print("RESULT_JSON:" + json.dumps(out))
        return
    elapsed = time.time() - t0
    m = rec.matched
    f = rec.fidelity
    out = {
        "route_id": rid,
        "mode": mode,
        "sigma_m": sigma,
        "elapsed_s": round(elapsed, 1),
        "waypoints": m.waypoints_used if m else 0,
        "snap_points": len(m.coords) if m else 0,
        "snap_length_m": round(m.length_m, 0) if m else 0,
        "matcher_mode": m.mode if m else None,
        "hmm_edges_emitted": m.hmm_states_emitted if m else 0,
        "hmm_unreachable_stitches": m.hmm_unreachable_stitches if m else 0,
        "unreachable_segments": m.unreachable_segments if m else 0,
        "fidelity": round(f.score, 3) if f else None,
        "frechet_m": round(f.frechet_m, 0) if f else None,
        "buffered_iou": round(f.buffered_iou, 3) if f else None,
        "confidence": round(rec.confidence, 3),
        "n_gcps": rec.diagnostics.get("n_gcps"),
        "failure": rec.failure,
    }
    print("RESULT_JSON:" + json.dumps(out))


if __name__ == "__main__":
    main()
