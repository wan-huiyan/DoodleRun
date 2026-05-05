"""Aggregate per-route reconstruction.json files into a single Phase 4a summary.

Usage:
    python -m stravart.poc.analyze \\
        --out-dir stravart/data/phase4a_poc \\
        [--md   stravart/data/phase4a_poc/results.md]

Emits:
    * stdout — human-readable summary of ship rate + per-stage funnel + per-route table
    * --md (optional) — markdown table that can be pasted into the handoff doc
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def classify(failure: str | None, shipped: bool) -> str:
    if shipped:
        return "shipped"
    if failure is None:
        return "unknown"
    f = failure.lower()
    if f.startswith("ocr: no street"):
        return "ocr_no_street_candidates"
    if f.startswith("ocr:"):
        return "ocr_other"
    if f.startswith("contour:"):
        return "contour"
    if f.startswith("crossref"):
        return "crossref_no_cluster"
    if f.startswith("georef: only"):
        return "georef_too_few_gcps"
    if f.startswith("georef:"):
        return "georef_other"
    if f.startswith("mapmatch"):
        return "mapmatch"
    if f.startswith("confidence:"):
        return "confidence_under_threshold"
    if f.startswith("fetch:"):
        return "image_fetch"
    if f.startswith("raised:") or f.startswith("hard:"):
        return "exception"
    return "other"


def load_summaries(out_dir: Path) -> list[dict]:
    base = out_dir / "per_image"
    summaries = []
    for d in sorted(base.iterdir()):
        f = d / "reconstruction.json"
        if f.exists():
            summaries.append(json.loads(f.read_text()))
    return summaries


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--md", type=Path, default=None)
    args = p.parse_args()

    rows = load_summaries(args.out_dir)
    n = len(rows)
    n_shipped = sum(1 for r in rows if r.get("shipped"))

    print(f"=== Phase 4a PoC summary — {n} routes ===\n")
    print(f"  shipped (gpx written, conf >= ~0.6):  {n_shipped}/{n}  =  {n_shipped/n:.0%}\n")

    # Stage funnel
    contour_ok = sum(1 for r in rows if (r["stages"].get("contour") or {}).get("polyline_points", 0) >= 10)
    ocr_ok = sum(1 for r in rows if (r["stages"].get("ocr") or {}).get("n_street_candidates", 0) > 0)
    cross_ok = sum(1 for r in rows if (r["stages"].get("crossref") or {}).get("cluster"))
    georef_ok = sum(1 for r in rows if r["stages"].get("georef"))
    map_ok = sum(1 for r in rows if (r["stages"].get("mapmatch") or {}).get("n_snapped_points", 0) > 0)

    print("Stage funnel (rows that reached / passed each stage):")
    print(f"  contour ≥ 10 px:        {contour_ok:>3}/{n}  ({contour_ok/n:.0%})")
    print(f"  OCR ≥ 1 street:         {ocr_ok:>3}/{n}  ({ocr_ok/n:.0%})")
    print(f"  crossref cluster:       {cross_ok:>3}/{n}  ({cross_ok/n:.0%})")
    print(f"  georef fit (≥3 GCPs):   {georef_ok:>3}/{n}  ({georef_ok/n:.0%})")
    print(f"  map-match snapped:      {map_ok:>3}/{n}  ({map_ok/n:.0%})")
    print(f"  shipped (conf ≥ 0.6):   {n_shipped:>3}/{n}  ({n_shipped/n:.0%})")
    print()

    # Failure modes
    bucket_counts: Counter = Counter(classify(r.get("failure"), r.get("shipped", False)) for r in rows)
    print("Failure-mode tally:")
    for mode, count in bucket_counts.most_common():
        print(f"  {mode:>30}  {count:>3}")
    print()

    # Per-route table
    print("Per-route detail:")
    print(f"  {'id':>5}  {'flag':>5}  {'conf':>5}  {'cands':>5}  {'gcps':>4}  {'rmse_m':>6}  {'fid':>4}  title  ::  failure")
    for r in rows:
        st = r["stages"]
        ocr = st.get("ocr") or {}
        cross = st.get("crossref") or {}
        georef = st.get("georef") or {}
        fid = st.get("fidelity") or {}
        diag = r.get("diagnostics") or {}
        ship = "SHIP" if r.get("shipped") else "FAIL"
        conf = r.get("confidence") or 0.0
        n_cands = ocr.get("n_street_candidates", 0)
        n_gcps = diag.get("n_gcps") if isinstance(diag, dict) else None
        if n_gcps is None:
            n_gcps = georef.get("n_anchors") if georef else 0
        rmse = georef.get("rmse_m") if georef else None
        fidsc = fid.get("score") if fid else None
        title = (r.get("title") or "")[:55]
        fail = r.get("failure") or ""
        rmse_s = f"{rmse:>6.1f}" if isinstance(rmse, (int, float)) else f"{'-':>6}"
        fid_s = f"{fidsc:.2f}" if isinstance(fidsc, (int, float)) else "  - "
        print(f"  {r['route_id']:>5}  {ship:>5}  {conf:>5.2f}  {n_cands:>5}  {n_gcps or 0:>4}  {rmse_s}  {fid_s:>4}  {title}  ::  {fail}")

    if args.md:
        with args.md.open("w") as f:
            f.write(f"# Phase 4a PoC results — {n} routes\n\n")
            f.write(f"**shipped:** {n_shipped}/{n} ({n_shipped/n:.0%}) at default threshold conf ≥ 0.6\n\n")
            f.write("## Stage funnel\n\n")
            f.write("| stage | passed | %n |\n|---|---:|---:|\n")
            f.write(f"| contour ≥ 10 px        | {contour_ok}/{n} | {contour_ok/n:.0%} |\n")
            f.write(f"| OCR ≥ 1 street         | {ocr_ok}/{n}     | {ocr_ok/n:.0%} |\n")
            f.write(f"| crossref cluster       | {cross_ok}/{n}   | {cross_ok/n:.0%} |\n")
            f.write(f"| georef fit (≥3 GCPs)   | {georef_ok}/{n}  | {georef_ok/n:.0%} |\n")
            f.write(f"| map-match snapped      | {map_ok}/{n}     | {map_ok/n:.0%} |\n")
            f.write(f"| **shipped (conf ≥ 0.6)** | **{n_shipped}/{n}** | **{n_shipped/n:.0%}** |\n\n")
            f.write("## Failure modes\n\n")
            f.write("| mode | count |\n|---|---:|\n")
            for mode, count in bucket_counts.most_common():
                f.write(f"| {mode} | {count} |\n")
            f.write("\n## Per-route detail\n\n")
            f.write("| id | flag | conf | candidates | GCPs | RMSE m | fidelity | title | failure |\n")
            f.write("|---:|:--|---:|---:|---:|---:|---:|---|---|\n")
            for r in rows:
                st = r["stages"]
                ocr = st.get("ocr") or {}
                cross = st.get("crossref") or {}
                georef = st.get("georef") or {}
                fid = st.get("fidelity") or {}
                diag = r.get("diagnostics") or {}
                ship = "SHIP" if r.get("shipped") else "FAIL"
                conf = r.get("confidence") or 0.0
                n_cands = ocr.get("n_street_candidates", 0)
                n_gcps = (diag.get("n_gcps") if isinstance(diag, dict) else None) or (georef.get("n_anchors") if georef else 0)
                rmse = georef.get("rmse_m") if georef else None
                fidsc = fid.get("score") if fid else None
                title = (r.get("title") or "").replace("|", "\\|")[:60]
                fail = (r.get("failure") or "").replace("|", "\\|")
                rmse_s = f"{rmse:.1f}" if isinstance(rmse, (int, float)) else "—"
                fid_s = f"{fidsc:.2f}" if isinstance(fidsc, (int, float)) else "—"
                f.write(f"| {r['route_id']} | {ship} | {conf:.2f} | {n_cands} | {n_gcps or 0} | {rmse_s} | {fid_s} | {title} | {fail} |\n")
            print(f"\nWrote markdown summary to {args.md}")


if __name__ == "__main__":
    main()
