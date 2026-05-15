"""Phase 4c Stream A — HMM map-matcher sweep with subprocess-isolated cells.

Runs the same single-image reconstruct pipeline as ``sweep_options.py`` but
varies ``mapmatch_mode`` between the legacy Dijkstra baseline and the new
HMM (Newson-Krumm via ``leuvenmapmatching``). Also sweeps the HMM ``σ``
(observation-noise standard deviation) over {20, 50, 100, 150} metres.

**RNG seed contamination fix (Phase 4c).** Phase 4b's `sweep_options.py`
re-seeded numpy + python random at the top of each loop iteration, but
that turned out NOT to be sufficient — ``reconstruct()`` calls
``leuvenmapmatching``/``osmnx``/``cv2.RANSAC`` internals that retain
state across calls inside one Python process. Empirically, the in-process
sweep produced fid=0.234 for the σ=50 HMM cell but the same parameters in
a fresh process gave fid=0.531 — a 2.3× swing entirely from interpreter
state, not algorithm differences. **Each cell now runs in a subprocess**
that imports the algorithm cold, seeds inside that fresh interpreter, and
prints one JSON result line. The orchestrator collects and ranks.

Run::

    python3 stravart/data/phase4b_diag/sweep_hmm.py 584
    python3 stravart/data/phase4b_diag/sweep_hmm.py 53

Writes ``sweep_hmm_<rid>.json`` alongside the existing ``sweep_<rid>.json``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


# (mapmatch_mode, hmm_obs_noise_m, label)
SWEEPS = [
    ("dijkstra",  0.0,  "baseline (Phase 4a Dijkstra, seed-pinned)"),
    ("hmm",       20.0, "HMM Viterbi σ=20m  (standard GPS noise)"),
    ("hmm",       50.0, "HMM Viterbi σ=50m  (default cartoon-projection)"),
    ("hmm",      100.0, "HMM Viterbi σ=100m (loose cartoon-projection)"),
    ("hmm",      150.0, "HMM Viterbi σ=150m (very loose)"),
]


def run_cell(rid: int, mode: str, sigma: float) -> dict:
    """Run one sweep cell in a fresh subprocess and parse its JSON output."""
    cell_script = ROOT / "stravart/data/phase4b_diag/sweep_hmm_cell.py"
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, str(cell_script), str(rid), mode, str(sigma)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    elapsed = time.time() - t0
    # Find the RESULT_JSON: line; other stdout (warnings, info logs) is ignored.
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT_JSON:"):
            try:
                return json.loads(line[len("RESULT_JSON:"):])
            except json.JSONDecodeError:
                pass
    return {
        "route_id": rid, "mode": mode, "sigma_m": sigma,
        "error": f"subprocess returned no RESULT_JSON (rc={proc.returncode})",
        "stderr_tail": proc.stderr.splitlines()[-5:] if proc.stderr else [],
        "elapsed_s": round(elapsed, 1),
    }


def main():
    rid = int(sys.argv[1]) if len(sys.argv) > 1 else 584

    results = []
    for mode, sigma, label in SWEEPS:
        print(f"\n=== {label} (mode={mode}, σ={sigma}m) ===", flush=True)
        out = run_cell(rid, mode, sigma)
        out["label"] = label
        results.append(out)
        print(json.dumps(out, indent=2))

    out_path = ROOT / f"stravart/data/phase4b_diag/sweep_hmm_{rid:05d}.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_path.relative_to(ROOT)}")

    print("\n--- comparison ---")
    print(f"{'label':<55} {'mode':>8} {'sigma':>5} {'wp':>4} "
          f"{'edges':>5} {'frechet':>7} {'fidelity':>8} {'iou':>5}")
    for r in results:
        fid = f"{r['fidelity']:.3f}" if r.get('fidelity') is not None else "  —  "
        iou = f"{r['buffered_iou']:.3f}" if r.get('buffered_iou') is not None else "  —  "
        print(f"{r['label']:<55} {r['mode']:>8} {r['sigma_m']:>5.0f} "
              f"{r.get('waypoints', 0):>4} "
              f"{r.get('hmm_edges_emitted', 0):>5} "
              f"{r.get('frechet_m') or 0:>7.0f} {fid:>8} {iou:>5}")


if __name__ == "__main__":
    main()
