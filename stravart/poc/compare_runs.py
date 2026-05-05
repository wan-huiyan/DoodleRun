"""Side-by-side compare of two PoC runs (pre-fix baseline vs post-fix).

Reads two parallel ``per_image/`` trees and emits a per-route delta table:
ship-status changes, confidence deltas, and stage-funnel improvements.

Usage:
    python -m stravart.poc.compare_runs \\
        --baseline stravart/data/phase4a_poc_run1 \\
        --fixed    stravart/data/phase4a_poc \\
        [--md docs/handoffs/_phase4a_compare.md]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_runs(base_dir: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    per_image = base_dir / "per_image"
    if not per_image.exists():
        return out
    for d in sorted(per_image.iterdir()):
        f = d / "reconstruction.json"
        if f.exists():
            j = json.loads(f.read_text())
            out[j["route_id"]] = j
    return out


def stage_status(j: dict) -> str:
    if j.get("shipped"):
        return "SHIP"
    f = (j.get("failure") or "").lower()
    if f.startswith("ocr: no"):
        return "OCR0"
    if f.startswith("ocr"):
        return "OCR-"
    if f.startswith("contour"):
        return "CONT"
    if f.startswith("crossref"):
        return "XREF"
    if f.startswith("georef"):
        return "GREF"
    if f.startswith("mapmatch"):
        return "MAP-"
    if f.startswith("confidence"):
        return "CONF"
    return "????"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", required=True, type=Path)
    p.add_argument("--fixed",    required=True, type=Path)
    p.add_argument("--md",       type=Path, default=None)
    args = p.parse_args()

    a = load_runs(args.baseline)
    b = load_runs(args.fixed)
    ids = sorted(set(a) | set(b))

    print(f"Baseline:  {args.baseline}  ({len(a)} routes)")
    print(f"Fixed:     {args.fixed}     ({len(b)} routes)")
    print()

    n_a_ship = sum(1 for j in a.values() if j.get("shipped"))
    n_b_ship = sum(1 for j in b.values() if j.get("shipped"))
    print(f"Ship rate: {n_a_ship}/{len(a)} → {n_b_ship}/{len(b)}  "
          f"(Δ {n_b_ship - n_a_ship:+d})")
    print()

    # Per-route table
    print(f"  {'id':>5} | {'baseline':>20}  | {'fixed':>20}  |   conf Δ")
    md_rows: list[str] = []
    for rid in ids:
        ja = a.get(rid)
        jb = b.get(rid)
        sa = stage_status(ja) if ja else "—"
        sb = stage_status(jb) if jb else "—"
        ca = ja.get("confidence", 0.0) if ja else 0.0
        cb = jb.get("confidence", 0.0) if jb else 0.0
        flag = ""
        if sa != "SHIP" and sb == "SHIP":
            flag = " ⬆ NEW SHIP"
        elif sa == "SHIP" and sb != "SHIP":
            flag = " ⬇ REGRESSION"
        elif sa != sb:
            flag = " (stage moved)"
        title = (jb or ja or {}).get("title", "")[:35]
        print(f"  {rid:>5} | {sa:>5} conf={ca:.2f}  | {sb:>5} conf={cb:.2f}  | {cb - ca:+.2f}{flag}  {title}")
        md_rows.append(
            f"| {rid} | {sa} | {ca:.2f} | {sb} | {cb:.2f} | {cb-ca:+.2f} | {title.replace('|','\\|')} |"
        )

    if args.md:
        with args.md.open("w") as f:
            f.write("# Phase 4a baseline vs fixed run\n\n")
            f.write(f"**Ship rate:** {n_a_ship}/{len(a)} → **{n_b_ship}/{len(b)}** (Δ {n_b_ship - n_a_ship:+d})\n\n")
            f.write("Stage codes: `SHIP` shipped · `OCR0` no street candidates · `OCR-` other OCR failure · "
                    "`XREF` no cluster · `GREF` GCP fit failed · `MAP-` map-match failed · "
                    "`CONF` below confidence threshold\n\n")
            f.write("| id | baseline stage | conf | fixed stage | conf | Δconf | title |\n")
            f.write("|---:|:--|---:|:--|---:|---:|---|\n")
            for r in md_rows:
                f.write(r + "\n")
        print(f"\nWrote {args.md}")


if __name__ == "__main__":
    main()
