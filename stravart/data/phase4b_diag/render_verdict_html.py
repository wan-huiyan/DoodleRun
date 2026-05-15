"""Render the Phase 4c verdict-comparison HTML report.

Produces ``stravart/data/phase4b_diag/verdict_comparison.html``, a
sortable / sticky-header dashboard summarising the curated-20 PoC outcomes
across Phase 4a → 4b → 4c. Distances are populated from:

* ``city_scale_summary.json`` (Phase 4b OCR0 routes — rendered offline)
* ``city_scale_phase4c_summary.json`` (Phase 4c C1-promoted routes — rendered
  offline by ``render_phase4c_city_scale.py``)
* For street-scale ships (#910, #921, #53, #584), the values are pinned from
  the persisted Phase 4a run #2 numbers, NOT live-recomputed (the live OCR
  + Nominatim + OSMnx graph download is the heavyweight step we skipped here).

Why generate vs hand-edit: per ``feedback_html_visual_reports.md`` the user
prefers HTML diagnostics; the table needs to stay in sync with the per-row
distance JSON. Inlines everything — opens via ``open <path>`` with no server.
"""

from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DIAG_DIR = ROOT / "stravart/data/phase4b_diag"


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    r_a, r_b = math.radians(a[0]), math.radians(b[0])
    dlat = r_b - r_a
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(r_a) * math.cos(r_b) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_000 * math.asin(min(1.0, math.sqrt(h)))


_PT_RE = re.compile(r'(?:rtept|trkpt) lat="([^"]+)" lon="([^"]+)"')


def _grounded_gpx_length_m(rid: int) -> float | None:
    """Sum haversine distances along the rtepts of ``route_<rid>/06_route.gpx``.

    Returns the persisted street-scale shipped polyline arc length for the
    Phase 4a strict ships, so we can populate the dashboard distance column
    from a real artifact rather than a guess. Returns ``None`` if no GPX
    was written (e.g. routes that failed at GPX-write stage).
    """
    path = ROOT / f"stravart/data/phase4a_poc/per_image/route_{rid:05d}/06_route.gpx"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    pts = [(float(a), float(b)) for a, b in _PT_RE.findall(text)]
    if len(pts) < 2:
        return None
    return sum(_haversine_m(p, q) for p, q in zip(pts, pts[1:]))


# --- per-route verdict table -------------------------------------------------
# Each row is a dict with the same keys; verdicts and distances are populated
# below from the JSON summaries + a small hand-traced street-scale block.
#
# Field meanings:
#   id               int
#   title            str
#   phase4a          short tag (verdict in Phase 4a)
#   phase4b          short tag (verdict in Phase 4b)
#   phase4c          short tag (verdict in Phase 4c — this branch)
#   tier             one of: "ship-strict" | "review" | "city-scale" | "fail"
#   distance_m       float or None
#   confidence       float or None
#   gcps             str (e.g. "5 unique, RMSE 5.46 m")
#   thumb            relative href for the diagnostic PNG, or None
#   note             freeform explanation
ROUTES = [
    # Strict ships (unchanged) — distances measured by haversine-summing the
    # rtepts of each route's Phase 4a 06_route.gpx (the persisted
    # ``matched.length_m`` at the time of ship). Computed live at HTML render
    # time; see ``_grounded_gpx_length_m`` below.
    dict(id=910, title="The London Marathon", phase4a="SHIP (0.60)",
         phase4b="SHIP-strict (0.60, kind=street)",
         phase4c="SHIP-strict (0.60, kind=street)",
         tier="ship-strict",
         distance_m=None,    # filled below from Phase 4a GPX
         confidence=0.60, gcps="5 unique, RMSE 5.46 m, fidelity 0.40",
         thumb="../phase4a_poc/diagnostics/route_00910_summary.png",
         note="unchanged through 4a→4b→4c. NOTE: GPX length << canonical 42.2km — the snap traced only a fragment of the cartoon path (Phase 3 known limitation, surfaced in Stream A/B follow-ups)."),
    dict(id=921, title="The Hackney Horse", phase4a="SHIP (0.62)",
         phase4b="SHIP-strict (0.62, kind=street)",
         phase4c="SHIP-strict (0.62, kind=street)",
         tier="ship-strict",
         distance_m=None,    # filled below from Phase 4a GPX
         confidence=0.62, gcps="6 unique, RMSE 5.37 m, fidelity 0.46",
         thumb="../phase4a_poc/diagnostics/route_00921_summary.png",
         note="animal-shape route in dense central London."),

    # Review tier — promoted in Phase 4b, unchanged in 4c.
    # NOTE: #53 and #584 have NO Phase 4a GPX file (they were FAIL-CONF in 4a;
    # only became review-tier in 4b). The numbers below are from the
    # sweep_XXX.json baseline lengths captured by Phase 4b's seeded sweep,
    # which IS a grounded artifact (live RANSAC-seeded re-run during 4b).
    dict(id=53, title="Regent's Park, Great Day For Doggin",
         phase4a="FAIL-CONF (0.58<0.60)",
         phase4b="REVIEW (0.58, kind=street)",
         phase4c="REVIEW (0.58, kind=street)",
         tier="review",
         distance_m=16_953.0,    # from sweep_00053.json baseline ('length' key)
         confidence=0.58, gcps="6 → 4 after RANSAC, RMSE 12.7 m, fidelity 0.36",
         thumb="../phase4a_poc/diagnostics/route_00053_summary.png",
         note="was silently dropped pre-4b; now reviewable. Distance from Phase 4b sweep_00053.json baseline."),
    dict(id=584, title="Travelling Elephant",
         phase4a="FAIL-CONF (0.50<0.60)",
         phase4b="REVIEW (0.50, kind=street)",
         phase4c="REVIEW (0.50, kind=street)",
         tier="review",
         distance_m=18_760.0,    # from sweep_00584.json baseline
         confidence=0.50, gcps="5 → 4 after RANSAC, RMSE 2.50 m, fidelity 0.19",
         thumb="../phase4a_poc/diagnostics/route_00584_summary.png",
         note="trunk takes wrong turn (Dijkstra picks shortest, not shape-best); see Stream A's HMM work. Distance from sweep_00584.json baseline."),

    # City-scale Phase 4b (OCR0 + title centroid) — distances computed by
    # render_city_scale.py
    # → 5, 30, 208, 248, 799, 800, 1135, 1359, 1565

    # City-scale Phase 4c (NEW: low-anchor / low-RMSE + title centroid) —
    # distances computed by render_phase4c_city_scale.py
    # → 577, 942, 1272

    # Honestly rejected
    dict(id=36, title="100k GPS Art Tour of West Devon",
         phase4a="FAIL-EARLY (OCR0)",
         phase4b="FAIL no-title-latlon",
         phase4c="FAIL no-title-latlon",
         tier="fail",
         distance_m=None, confidence=None,
         gcps="0 streets, no title centroid",
         thumb="../phase4a_poc/diagnostics/route_00036_summary.png",
         note="Phase 1 couldn't geocode 'West Devon'; no anchor to fall back on."),
    dict(id=60, title="Doggin' My Way Through Hampstead Heath",
         phase4a="FAIL-CONF (0.28)",
         phase4b="FAIL-conf (0.28<0.4)",
         phase4c="FAIL no-title-latlon",
         tier="fail",
         distance_m=None, confidence=0.28,
         gcps="5 → 3 after RANSAC, RMSE ≈ 0 (degenerate)",
         thumb="../phase4a_poc/diagnostics/route_00060_summary.png",
         note="C1 fall-through would have caught this, BUT Phase 1 has lat=None for it — needs an upstream geocode pass."),
    dict(id=1294, title="A Whale in Wales",
         phase4a="FAIL-CONF (0.24)",
         phase4b="FAIL min_gcps (3<5)",
         phase4c="FAIL no-title-latlon",
         tier="fail",
         distance_m=None, confidence=0.24,
         gcps="3 in a country-sized area",
         thumb="../phase4a_poc/diagnostics/route_01294_summary.png",
         note="'Wales' too broad for triangulation; Phase 1 lat=None blocks C1 fall-through."),
    dict(id=1333, title="Paris GPS Drawing",
         phase4a="FAIL-XREF (1 candidate)",
         phase4b="FAIL-XREF (1 candidate)",
         phase4c="FAIL-XREF (1 candidate)",
         tier="fail",
         distance_m=None, confidence=None,
         gcps="1 OCR candidate — no consensus cluster",
         thumb="../phase4a_poc/diagnostics/route_01333_summary.png",
         note="C1 fall-through fires on min_gcps/min_rmse fail, NOT on crossref-no-consensus. Known gap."),
]


def _merge_city_scale(summary_path: Path, *, kind_label: str, phase_promoted: str,
                      phase4a_tag: str, phase4b_tag: str | None):
    """Append rows for each entry in a city-scale JSON summary."""
    data = json.loads(summary_path.read_text())
    title_overrides = {
        5: "Manchester Dog",
        30: "Vienna Doggo",
        208: "Berlin Mutt",
        248: "1st Berlin Drawing",
        799: "Bullfight in Munich",
        800: "Munich Lion",
        1135: "Rotterdam Has Added Two Turtles",
        1359: "Amsterdam is Ajax",
        1565: "Strava Logo in Hamburg",
        577: "Dumbo Visits Cambridge",
        942: "London Bear Half Marathon",
        1272: "St Albans Shark",
    }
    # Per-route Phase 4b verdict for the C1-promoted rows (matches the
    # original verdict HTML's per-route summaries).
    phase4b_per_route = {
        577: "FAIL min_gcps (3<5)",
        942: "FAIL-conf (0.31<0.4) — degenerate",
        1272: "FAIL min_gcps (4<5)",
    }
    for row in data:
        rid = row["rid"]
        title = title_overrides.get(rid, row["title"][:40])
        ROUTES.append(dict(
            id=rid, title=title,
            phase4a=phase4a_tag,
            phase4b=phase4b_tag or phase4b_per_route.get(rid, "FAIL"),
            phase4c=f"{kind_label} (conf 0.50, decorative)",
            tier="city-scale",
            distance_m=row["total_distance_m"],
            confidence=0.50,
            gcps=f"{row['n_segments']} segments, {row['n_polyline']} pts · "
                 f"bbox {row['bbox_width_m']:.0f}m × {row['bbox_height_m']:.0f}m",
            thumb=row["out"].replace("stravart/data/phase4b_diag/", ""),
            note=phase_promoted,
        ))


# City-scale fallback existing routes (Phase 4b)
_merge_city_scale(
    DIAG_DIR / "city_scale_summary.json",
    kind_label="CITY-SCALE",
    phase_promoted="city-scale ship via Phase 4b OCR0 fallback (unchanged in 4c)",
    phase4a_tag="FAIL-EARLY (OCR0)",
    phase4b_tag="CITY-SCALE (0.50, kind=city-scale)",
)

# Phase 4c NEW promotions (low-anchor / low-RMSE + title centroid)
_merge_city_scale(
    DIAG_DIR / "city_scale_phase4c_summary.json",
    kind_label="CITY-SCALE-NEW",
    phase_promoted="NEW in 4c: C1 fall-through promoted from fail → decorative",
    phase4a_tag="FAIL-CONF or FAIL-EARLY",
    phase4b_tag=None,    # use per-route
)


# Populate the two strict ships' distances from their Phase 4a GPX (grounded).
for _r in ROUTES:
    if _r["tier"] == "ship-strict" and _r["distance_m"] is None:
        _r["distance_m"] = _grounded_gpx_length_m(_r["id"])


# Order rows: ships → reviews → city-scale → city-scale-new → fails, then by id
TIER_ORDER = {"ship-strict": 0, "review": 1, "city-scale": 2, "fail": 3}
def _row_label(r):
    if r["phase4c"].startswith("CITY-SCALE-NEW"):
        return (2.5, r["id"])    # group new city-scale just after Phase 4b city-scale
    return (TIER_ORDER[r["tier"]], r["id"])
ROUTES.sort(key=_row_label)


# --- tallies -----------------------------------------------------------------

def _tally():
    by_tier = {"ship-strict": [], "review": [], "city-scale-4b": [], "city-scale-4c": [], "fail": []}
    for r in ROUTES:
        if r["phase4c"].startswith("CITY-SCALE-NEW"):
            by_tier["city-scale-4c"].append(r)
        elif r["tier"] == "city-scale":
            by_tier["city-scale-4b"].append(r)
        else:
            by_tier[r["tier"]].append(r)
    sums = {k: sum((r["distance_m"] or 0.0) for r in v) for k, v in by_tier.items()}
    counts = {k: len(v) for k, v in by_tier.items()}
    return counts, sums


# --- HTML rendering ----------------------------------------------------------

def _fmt_distance(m: float | None) -> str:
    if m is None:
        return "—"
    if m >= 1_000.0:
        return f"{m/1_000:.1f}&nbsp;km"
    return f"{m:.0f}&nbsp;m"


def _badge(tier: str, label: str) -> str:
    css = {"ship-strict": "ship", "review": "review", "city-scale": "city", "fail": "fail"}[tier]
    if "NEW" in label:
        css = "city-new"
    return f'<span class="badge {css}">{html.escape(label)}</span>'


def render_html() -> str:
    counts, sums = _tally()
    ship_total = sums["ship-strict"] + sums["review"]
    decorative_total = sums["city-scale-4b"] + sums["city-scale-4c"]
    grand_total = ship_total + decorative_total
    n_with_output = (counts["ship-strict"] + counts["review"]
                     + counts["city-scale-4b"] + counts["city-scale-4c"])

    rows_html = []
    for r in ROUTES:
        thumb_html = (
            f'<a href="{html.escape(r["thumb"])}" target="_blank">'
            f'<img src="{html.escape(r["thumb"])}" alt="{html.escape(r["title"])}"></a>'
            if r["thumb"] else '<span class="nopic">no thumbnail</span>'
        )
        # tier label for the badge column reflects Phase 4c outcome
        if r["phase4c"].startswith("SHIP-strict"):
            badge_label, tier_sort = "SHIP", "ship-strict"
        elif r["phase4c"].startswith("REVIEW"):
            badge_label, tier_sort = "REVIEW", "review"
        elif r["phase4c"].startswith("CITY-SCALE-NEW"):
            badge_label, tier_sort = "CITY-SCALE-NEW", "city-scale"
        elif r["phase4c"].startswith("CITY-SCALE"):
            badge_label, tier_sort = "CITY-SCALE", "city-scale"
        else:
            badge_label, tier_sort = "FAIL", "fail"
        rows_html.append(
            f'<tr data-tier="{tier_sort}" data-dist="{r["distance_m"] or 0}">'
            f'<td class="rid">{r["id"]}</td>'
            f'<td class="title">{html.escape(r["title"])}</td>'
            f'<td>{_badge(tier_sort, badge_label)}</td>'
            f'<td class="num">{_fmt_distance(r["distance_m"])}</td>'
            f'<td class="num">{(f"{r["confidence"]:.2f}" if r["confidence"] is not None else "—")}</td>'
            f'<td class="small">{html.escape(r["phase4a"])}</td>'
            f'<td class="small">{html.escape(r["phase4b"])}</td>'
            f'<td class="small">{html.escape(r["phase4c"])}</td>'
            f'<td class="thumb">{thumb_html}</td>'
            f'<td class="note">{html.escape(r["note"])}</td>'
            f'</tr>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>strav.art Phase 4c verdict — curated-20 dashboard</title>
<style>
  :root {{
    --bg: #fafafa;
    --fg: #1a1a1a;
    --muted: #666;
    --accent: #c1432d;
    --row-alt: #f5f5f5;
    --ship: #1f8a3a;
    --review: #b07c1a;
    --city: #2a6fb8;
    --city-new: #5e3d99;
    --fail: #888;
    --border: #d8d8d8;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--bg); color: var(--fg);
    margin: 0;
    -webkit-font-smoothing: antialiased;
  }}
  body {{ padding: 2rem 1.5rem; line-height: 1.45; }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  h1 {{ font-size: 1.65rem; font-weight: 600; margin: 0 0 0.4rem; }}
  h2 {{ font-size: 1.15rem; font-weight: 600; margin: 2rem 0 0.6rem; border-bottom: 1px solid var(--border); padding-bottom: 0.3rem; }}
  .meta {{ color: var(--muted); font-size: 0.92rem; margin-bottom: 1.2rem; }}
  code {{ font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 0.86em; background: #eaeaea; padding: 0.05em 0.3em; border-radius: 2px; }}
  blockquote {{ border-left: 3px solid var(--accent); padding-left: 0.9rem; color: #444; margin: 0.8rem 0 1.2rem; }}

  /* KPI tiles at top — design-inspired by route-tracker dashboards */
  .kpis {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 0.8rem;
    margin: 1rem 0 1.6rem;
  }}
  .kpi {{
    background: white;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.8rem 1rem;
    position: relative;
    overflow: hidden;
  }}
  .kpi::before {{
    content: ""; position: absolute; top: 0; left: 0; width: 4px; height: 100%;
    background: var(--bar, var(--muted));
  }}
  .kpi.ship   {{ --bar: var(--ship); }}
  .kpi.review {{ --bar: var(--review); }}
  .kpi.city   {{ --bar: var(--city); }}
  .kpi.city-new {{ --bar: var(--city-new); }}
  .kpi.fail   {{ --bar: var(--fail); }}
  .kpi.total  {{ --bar: var(--accent); }}
  .kpi h4 {{ margin: 0 0 0.25rem; font-size: 0.78rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }}
  .kpi .v {{ font-size: 1.7rem; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.15; }}
  .kpi .d {{ font-size: 0.82rem; color: var(--muted); margin-top: 0.1rem; }}

  /* Sortable, sticky-header table */
  .table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 6px; background: white; }}
  table.verdict {{
    width: 100%; border-collapse: collapse; font-size: 0.86rem;
    table-layout: auto;
  }}
  table.verdict thead th {{
    position: sticky; top: 0; z-index: 2;
    background: #f0f0f0; border-bottom: 2px solid var(--border);
    padding: 0.55rem 0.6rem; text-align: left; font-weight: 600;
    cursor: pointer; user-select: none;
    white-space: nowrap;
  }}
  table.verdict thead th:hover {{ background: #e6e6e6; }}
  table.verdict thead th.sorted-asc::after {{ content: " ▲"; color: var(--accent); }}
  table.verdict thead th.sorted-desc::after {{ content: " ▼"; color: var(--accent); }}
  table.verdict tbody td {{
    padding: 0.5rem 0.6rem; border-bottom: 1px solid #eee; vertical-align: top;
  }}
  table.verdict tbody tr:nth-child(odd) td {{ background: var(--row-alt); }}
  table.verdict tbody tr:hover td {{ background: #f3e9e7; }}
  td.rid {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
  td.title {{ font-weight: 600; min-width: 200px; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  td.small {{ font-size: 0.78rem; color: #444; }}
  td.thumb img {{ max-width: 180px; max-height: 110px; border: 1px solid #ccc; border-radius: 3px; display: block; }}
  td.note {{ font-size: 0.78rem; color: #444; max-width: 320px; }}
  .nopic {{ display: inline-block; padding: 0.5rem; border: 1px dashed #ccc; color: var(--muted); font-size: 0.75rem; border-radius: 3px; }}

  .badge {{ display: inline-block; padding: 0.1rem 0.45rem; border-radius: 3px;
            font-size: 0.72rem; font-weight: 700; color: white; letter-spacing: 0.02em;
            white-space: nowrap; }}
  .badge.ship      {{ background: var(--ship); }}
  .badge.review    {{ background: var(--review); }}
  .badge.city      {{ background: var(--city); }}
  .badge.city-new  {{ background: var(--city-new); }}
  .badge.fail      {{ background: var(--fail); }}

  .legend {{ display: flex; gap: 1rem; flex-wrap: wrap; font-size: 0.85rem; margin: 0.5rem 0 1rem; color: #444; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 0.35rem; }}

  details {{ background: white; border: 1px solid var(--border); border-radius: 4px; padding: 0.5rem 0.9rem; margin: 0.6rem 0; }}
  details summary {{ cursor: pointer; font-weight: 600; }}
  details ul {{ margin: 0.4rem 0 0.2rem; padding-left: 1.2rem; }}
</style>
</head>
<body>
<div class="container">

<h1>strav.art Phase 4c — curated-20 verdict dashboard</h1>
<p class="meta">
  Branch <code>claude/stravart-phase4c-dashboard-distance</code> · paper-trace
  against the persisted Phase 4a run #2 numbers plus Phase 4b sweep data plus
  Phase 4c offline-rendered city-scale fallbacks. Re-render with
  <code>python3 stravart/data/phase4b_diag/render_verdict_html.py</code>.
</p>

<blockquote>
  <strong>What's new in Phase 4c.</strong> C1 extends
  <code>_city_scale_fallback</code> to fire when the affine fit fails at
  the <code>min_gcps</code> or <code>min_rmse</code> gate AND a title-derived
  lat/lon is available — promoting routes that previously hard-failed to a
  decorative city-scale ship. C2 adds a per-route
  <code>total_distance_m</code> (snapped polyline length for street-scale,
  per-segment haversine sum for city-scale). C3 rebuilds this dashboard with
  KPI tiles, a distance column, sortable columns, and a sticky header.
</blockquote>

<h2>KPI tiles</h2>
<div class="kpis">
  <div class="kpi ship">
    <h4>Strict ship</h4>
    <div class="v">{counts["ship-strict"]}<span style="font-weight:400; font-size:1rem; color:var(--muted)"> / 20</span></div>
    <div class="d">{_fmt_distance(sums["ship-strict"])} runnable</div>
  </div>
  <div class="kpi review">
    <h4>Review tier</h4>
    <div class="v">{counts["review"]}<span style="font-weight:400; font-size:1rem; color:var(--muted)"> / 20</span></div>
    <div class="d">{_fmt_distance(sums["review"])} runnable*</div>
  </div>
  <div class="kpi city">
    <h4>City-scale (4b)</h4>
    <div class="v">{counts["city-scale-4b"]}<span style="font-weight:400; font-size:1rem; color:var(--muted)"> / 20</span></div>
    <div class="d">{_fmt_distance(sums["city-scale-4b"])} decorative</div>
  </div>
  <div class="kpi city-new">
    <h4>City-scale (4c NEW)</h4>
    <div class="v">{counts["city-scale-4c"]}<span style="font-weight:400; font-size:1rem; color:var(--muted)"> / 20</span></div>
    <div class="d">{_fmt_distance(sums["city-scale-4c"])} decorative</div>
  </div>
  <div class="kpi fail">
    <h4>Honest fails</h4>
    <div class="v">{counts["fail"]}<span style="font-weight:400; font-size:1rem; color:var(--muted)"> / 20</span></div>
    <div class="d">no GPX produced</div>
  </div>
  <div class="kpi total">
    <h4>Total output</h4>
    <div class="v">{n_with_output}<span style="font-weight:400; font-size:1rem; color:var(--muted)"> / 20</span></div>
    <div class="d">{_fmt_distance(grand_total)} all-tier distance</div>
  </div>
</div>

<div class="legend">
  <span><span class="badge ship">SHIP</span> runnable, ≥0.6 confidence</span>
  <span><span class="badge review">REVIEW</span> runnable, needs approval</span>
  <span><span class="badge city">CITY-SCALE</span> decorative (Phase 4b)</span>
  <span><span class="badge city-new">CITY-SCALE-NEW</span> decorative (Phase 4c C1)</span>
  <span><span class="badge fail">FAIL</span> no output</span>
</div>

<h2>Per-route verdicts (sortable — click a column header)</h2>
<p class="meta" style="margin-bottom:0.6rem">
  Sorted by tier ⟶ ID by default. Click any header to re-sort. Click a
  thumbnail to open the full diagnostic PNG.
</p>

<div class="table-wrap">
<table class="verdict" id="vtable">
  <thead>
    <tr>
      <th data-key="id">#</th>
      <th data-key="title">Title</th>
      <th data-key="tier">Verdict</th>
      <th data-key="dist">Distance</th>
      <th data-key="conf">Conf</th>
      <th data-key="p4a">Phase 4a</th>
      <th data-key="p4b">Phase 4b</th>
      <th data-key="p4c">Phase 4c</th>
      <th>Thumbnail</th>
      <th>Notes</th>
    </tr>
  </thead>
  <tbody>
    {''.join(rows_html)}
  </tbody>
</table>
</div>

<h2>Tallies (Phase 4c)</h2>
<details open>
  <summary>Detailed counts + distances</summary>
  <ul>
    <li><strong>Strict ship:</strong> {counts["ship-strict"]} / 20 · {_fmt_distance(sums["ship-strict"])} runnable total</li>
    <li><strong>Review tier:</strong> {counts["review"]} / 20 · {_fmt_distance(sums["review"])} runnable total</li>
    <li><strong>City-scale (Phase 4b OCR0 fallback):</strong> {counts["city-scale-4b"]} / 20 · {_fmt_distance(sums["city-scale-4b"])} decorative total</li>
    <li><strong>City-scale (Phase 4c NEW fallback):</strong> {counts["city-scale-4c"]} / 20 · {_fmt_distance(sums["city-scale-4c"])} decorative total</li>
    <li><strong>Honestly rejected:</strong> {counts["fail"]} / 20</li>
    <li><strong>Total ship-tier distance (street-scale ships + reviews):</strong> {_fmt_distance(ship_total)}</li>
    <li><strong>Total all-tier distance (incl. decorative city-scale):</strong> {_fmt_distance(grand_total)}</li>
  </ul>
</details>

<h2>What changed vs Phase 4b</h2>
<ul>
  <li><strong>C1 fall-through</strong> promoted 3 routes from FAIL → CITY-SCALE
      (Dumbo Visits Cambridge, London Bear Half Marathon, St Albans Shark).
      Each has a Phase 1 title centroid and was previously dropped by the
      <code>min_gcps</code> / <code>min_rmse</code> gate.</li>
  <li><strong>2 spec candidates remain hard fails</strong> (#60 Hampstead Heath,
      #1294 Whale in Wales) because their Phase 1 row has <code>lat=NULL</code>
      — C1's fall-through correctly requires a title centroid, so closing
      this last gap is upstream geocoder work.</li>
  <li><strong>Total catalog ship rate: 13 / 20 → 16 / 20</strong> (street-scale
      + city-scale shipped or decoratively shipped). The strict + review
      runnable count is unchanged at 4 / 20 — C1 only widens the decorative
      tier.</li>
</ul>

</div>
<script>
// Vanilla-JS column sorter — no framework deps so the file opens via `open`
// in any browser without a server.
(function () {{
  const table = document.getElementById("vtable");
  if (!table) return;
  const tbody = table.tBodies[0];
  const headers = table.tHead.rows[0].cells;

  function cellValue(row, idx, key) {{
    const cell = row.cells[idx];
    if (!cell) return "";
    if (key === "id") return parseInt(cell.textContent.trim(), 10) || 0;
    if (key === "dist") return parseFloat(row.dataset.dist) || 0;
    if (key === "conf") {{
      const v = parseFloat(cell.textContent);
      return Number.isFinite(v) ? v : -1;
    }}
    if (key === "tier") {{
      const order = {{"ship-strict":0, "review":1, "city-scale":2, "fail":3}};
      return (order[row.dataset.tier] ?? 9);
    }}
    return cell.textContent.trim().toLowerCase();
  }}

  Array.from(headers).forEach((th, idx) => {{
    const key = th.dataset.key;
    if (!key) return;
    th.addEventListener("click", () => {{
      const asc = !th.classList.contains("sorted-asc");
      Array.from(headers).forEach(h => h.classList.remove("sorted-asc", "sorted-desc"));
      th.classList.add(asc ? "sorted-asc" : "sorted-desc");
      const rows = Array.from(tbody.rows);
      rows.sort((a, b) => {{
        const av = cellValue(a, idx, key);
        const bv = cellValue(b, idx, key);
        if (av < bv) return asc ? -1 : 1;
        if (av > bv) return asc ? 1 : -1;
        return 0;
      }});
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});
}})();
</script>
</body>
</html>
"""


def main():
    out = DIAG_DIR / "verdict_comparison.html"
    out.write_text(render_html())
    print(f"wrote {out.relative_to(ROOT)}  ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
