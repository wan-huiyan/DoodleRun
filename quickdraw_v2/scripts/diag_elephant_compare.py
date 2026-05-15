"""Compact 2-panel comparison: raw strokes vs final pointcloud, for top 30 elephants.

Focuses the eye on whether the extraction is faithful (same shape as raw drawing)
or whether it's losing features (trunk, legs, tail).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_outlines as eo


def main():
    root = Path(__file__).resolve().parent.parent
    raw = root / "data" / "elephant.recognized.ndjson"
    out_path = root / "diagnostics" / "elephant_compare_top30.png"

    template_dir = root / "sketches" / "elephant"
    top = []
    for f in sorted(template_dir.glob("*.json")):
        d = json.loads(f.read_text())
        if d.get("rank", 9999) < 30:
            top.append((d["rank"], str(d["key_id"])))
    top.sort()
    wanted = {kid: rank for rank, kid in top}

    records_by_rank: dict[int, dict] = {}
    with raw.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            kid = str(rec.get("key_id"))
            if kid in wanted:
                records_by_rank[wanted[kid]] = rec
                if len(records_by_rank) == len(wanted):
                    break

    # 6 cols x 10 rows = 60 sub-panels. Each elephant uses 2 (raw, pc) side by side.
    # So 6 elephants per row x 5 rows = 30 elephants.
    n_per_row = 6
    n_rows = 5
    fig, axes = plt.subplots(n_rows * 2, n_per_row, figsize=(n_per_row * 2.4, n_rows * 4.0))
    for rank in range(30):
        rec = records_by_rank.get(rank)
        row, col = (rank // n_per_row) * 2, rank % n_per_row
        ax_raw = axes[row, col]
        ax_pc = axes[row + 1, col]
        if rec is None:
            ax_raw.set_visible(False); ax_pc.set_visible(False)
            continue
        # Raw strokes
        cmap = plt.cm.tab10
        for i, s in enumerate(rec.get("drawing", [])):
            if len(s[0]) < 2:
                continue
            ax_raw.plot(s[0], s[1], color=cmap(i % 10), linewidth=1.2)
        ax_raw.set_aspect("equal"); ax_raw.invert_yaxis()
        ax_raw.set_xticks([]); ax_raw.set_yticks([])
        ax_raw.set_title(f"Q{rank+1:02d} raw", fontsize=8)
        # Final pointcloud
        res = eo.extract(rec)
        if res.reason == "ok":
            xs = [p[0] for p in res.points]
            ys = [p[1] for p in res.points]
            ax_pc.scatter(xs, ys, s=0.3, c="black")
        ax_pc.set_aspect("equal")
        ax_pc.set_xticks([]); ax_pc.set_yticks([])
        ax_pc.set_title(f"Q{rank+1:02d} extracted (n={res.n_points})", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, facecolor="white")
    plt.close(fig)
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
