"""Generate an HTML dashboard summarising every elephant search run in
multi_template/previews/. Auto-scans for *_summary.json, big PNGs, diagnostic
PNGs, contact sheets. Run after each experiment; open the dashboard in a
browser to compare iterations at any time.

Path: multi_template/previews/dashboard.html
"""
from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path
from typing import Optional


PREVIEWS_DIR = Path("multi_template/previews")
DASHBOARD_PATH = PREVIEWS_DIR / "dashboard.html"


CSS = """
body { font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       margin: 24px; max-width: 1400px; background: #fafafa; color: #222; }
h1 { margin: 0 0 6px 0; }
.muted { color: #666; font-size: 12px; }
.section { margin: 32px 0; padding: 18px; background: white;
           border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
h2 { margin-top: 0; border-bottom: 1px solid #eee; padding-bottom: 6px; }
.runs { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.run { border: 1px solid #e0e0e0; border-radius: 6px; padding: 12px;
       background: #fdfdfd; }
.run img { width: 100%; height: auto; display: block; border-radius: 4px; }
.run h3 { margin: 0 0 6px 0; font-size: 15px; }
.run .meta { font-size: 12px; color: #555; margin-bottom: 8px;
             font-family: ui-monospace, Menlo, monospace; }
.locked { border: 2px solid #4caf50; }
.locked h3::before { content: "🔒 LOCKED — "; color: #4caf50; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #eee; }
th { background: #f5f5f5; }
.best { background: #e8f5e9; }
.suspect { background: #ffebee; }
a { color: #1565c0; text-decoration: none; }
a:hover { text-decoration: underline; }
.thumb-row { display: flex; gap: 12px; flex-wrap: wrap; }
.thumb-row img { max-width: 280px; height: auto; border: 1px solid #ddd;
                 border-radius: 4px; }
"""


def find_runs(animal: str = "elephant"):
    runs = []
    for summary in sorted(PREVIEWS_DIR.glob(f"{animal}_*_summary.json")):
        try:
            meta = json.loads(summary.read_text())
        except Exception:
            continue
        runs.append((summary, meta))
    return runs


def render_dashboard():
    runs = find_runs("elephant")
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    locked_cfg = None
    locked_path = Path("multi_template/locked_routes.json")
    if locked_path.exists():
        try:
            locked_cfg = json.loads(locked_path.read_text())
        except Exception:
            locked_cfg = None

    body = [
        f'<h1>DoodleRun elephant — progress dashboard</h1>',
        f'<div class="muted">Generated {now} · file: {DASHBOARD_PATH}</div>',
    ]

    # Locked section
    if locked_cfg:
        body.append('<div class="section locked-section">')
        body.append('<h2>🔒 Currently locked routes</h2>')
        body.append('<div class="runs">')
        for loc_key in ("st_albans", "milton_keynes", "maidenhead_windsor"):
            sub_key = f"elephant_{loc_key}"
            if sub_key not in locked_cfg:
                continue
            sub = locked_cfg[sub_key]
            big_png = PREVIEWS_DIR / "big" / f"BIG_elephant_{loc_key}_s04_xs.png"
            locked_png = PREVIEWS_DIR / "locked" / f"LOCKED_elephant_{loc_key}.png"
            img = locked_png if locked_png.exists() else big_png
            img_rel = img.relative_to(PREVIEWS_DIR) if img.exists() else None
            body.append('<div class="run locked">')
            body.append(f"<h3>{loc_key}</h3>")
            body.append(
                f'<div class="meta">{sub["vote_id"]} ({sub["source"]}) · '
                f'scale={sub["scale_m"]/1000:.2f}km · rot={sub["rotation_deg"]:+.1f}° · '
                f'{sub["route_length_m"]/1000:.1f} km · iou={sub["fidelity"]["iou"]:.3f}</div>'
            )
            if img_rel:
                body.append(f'<img src="{html.escape(str(img_rel))}" alt="{loc_key}">')
            else:
                body.append('<div class="muted">No PNG yet</div>')
            body.append("</div>")
        body.append("</div></div>")

    # All runs section, grouped by suffix
    by_suffix: dict[str, list] = {}
    for summary_path, meta in runs:
        # Parse suffix from filename: elephant_{location}_{suffix}_summary.json
        stem = summary_path.stem  # elephant_st_albans_s04_xs_summary
        # Strip leading "elephant_" and trailing "_summary"
        rest = stem[len("elephant_"):][: -len("_summary")]
        # Try to split into location + suffix; location can have underscores
        # Known locations:
        for loc in ("st_albans", "milton_keynes", "maidenhead_windsor", "hertford", "outer_london", "cambridge"):
            if rest.startswith(loc):
                suffix = rest[len(loc):].lstrip("_") or "(default)"
                by_suffix.setdefault(suffix, []).append((loc, summary_path, meta))
                break

    # Order suffixes by most recent file mtime
    suffix_mtimes = {
        s: max(p.stat().st_mtime for _, p, _ in entries)
        for s, entries in by_suffix.items()
    }
    suffix_order = sorted(by_suffix.keys(), key=lambda s: -suffix_mtimes[s])

    for suffix in suffix_order:
        entries = sorted(by_suffix[suffix], key=lambda t: t[0])
        body.append(f'<div class="section">')
        body.append(f'<h2>Run: <code>{html.escape(suffix)}</code></h2>')
        body.append(f'<div class="runs">')
        for loc, summary_path, meta in entries:
            best = meta["best"]
            iou = best["fidelity"]["iou"]
            # Find best per-rank rendered PNG
            top_png = None
            for png in sorted(PREVIEWS_DIR.glob(f"elephant_{loc}_{suffix}_top01_*.png")):
                top_png = png
                break
            big_png = PREVIEWS_DIR / "big" / f"BIG_elephant_{loc}_{suffix}.png"
            diag_png = PREVIEWS_DIR / "diagnostic" / f"DIAG_elephant_{loc}_{suffix}.png"
            pick_png = PREVIEWS_DIR / f"_PICK_elephant_{loc}_{suffix}.png"

            body.append('<div class="run">')
            body.append(f'<h3>{loc} — iou {iou:.3f}</h3>')
            body.append(
                f'<div class="meta">{best["vote_id"]} ({best["source"]}) · '
                f'scale={best["scale_m"]/1000:.2f}km · rot={best["rotation_deg"]:+.1f}° · '
                f'{best["route_length_m"]/1000:.1f} km · frechet={best["fidelity"]["frechet"]:.3f}</div>'
            )
            # Primary image — prefer big, fallback to top-01
            primary = big_png if big_png.exists() else top_png
            if primary and primary.exists():
                rel = primary.relative_to(PREVIEWS_DIR)
                body.append(f'<img src="{html.escape(str(rel))}" alt="{loc} {suffix}">')
            # Secondary: diagnostic / pick sheets
            sec_links = []
            for name, p in (("top-01", top_png), ("big", big_png), ("diagnostic", diag_png), ("pick-sheet", pick_png)):
                if p and p.exists():
                    rel = p.relative_to(PREVIEWS_DIR)
                    sec_links.append(f'<a href="{html.escape(str(rel))}" target="_blank">{name}</a>')
            if sec_links:
                body.append(f'<div class="meta">{" · ".join(sec_links)}</div>')
            body.append("</div>")
        body.append("</div></div>")

    # Template gallery
    gallery = PREVIEWS_DIR / "_GALLERY_elephant.png"
    if gallery.exists():
        body.append('<div class="section">')
        body.append('<h2>Approved template gallery</h2>')
        body.append(f'<img src="{gallery.name}" alt="gallery">')
        body.append("</div>")

    html_doc = (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>DoodleRun elephant progress</title>'
        f'<style>{CSS}</style>'
        '</head><body>'
        + "\n".join(body)
        + "</body></html>"
    )
    DASHBOARD_PATH.write_text(html_doc)
    print(f"wrote {DASHBOARD_PATH}")
    print(f"  open: file://{DASHBOARD_PATH.resolve()}")


if __name__ == "__main__":
    render_dashboard()
