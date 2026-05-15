# strav.art Phase 4b — Wrap Handoff

**Branch:** `claude/stravart-phase4b-tighten-fallback` (pushed, no PR — user holds merge call)
**Predecessor:** `docs/handoffs/stravart_phase4a_results.md`
**Date:** 2026-05-15
**Status:** 7 commits landed; 4 wins, 3 documented negative results; 3 parallel streams queued for the next session.

---

## What was completed

### Wins (shipped + verified)

| Area | Change | Effect |
|---|---|---|
| **Tighter gate** | min_gcps=5, geo-dedup of GCPs within 5m, hull-spread, RMSE≥0.5m anti-degeneracy | Rejects degenerate fits (3-4 GCP underdetermined cases like St Albans Shark, Whale-Wales, Dumbo Cambridge). Same 2/20 strict-ship rate but with HONEST failure reasons. |
| **Review tier** | min_confidence=0.4 default + strict_threshold=0.6; `kind` + `review_status` columns on `routes` table | Routes at conf 0.4-0.6 (Regent's Park, Travelling Elephant) ship as `review` instead of silent fail. |
| **City-scale fallback** | New `stravart/centroid_project.py`; orchestrator falls back when OCR finds zero streets AND a title-derived lat/lon is supplied | 9 of 10 OCR0 routes in the curated 20 now produce decorative city-scale GPX (was: hard fail). `kind="city-scale"`, `is_runnable=False`. |
| **Multi-polyline contour trace (BIG WIN)** | New `contour.trace_all_polylines` decomposes the skeleton into ALL its simple-path edges (one polyline per node-to-node graph edge) | Was losing **30–75% of the skeleton** on branching cartoons. Manchester Dog 30.8%→100%; Munich Lion 24.7%→100%; even shipped London Marathon 35.9%→100% coverage. |
| **Multi-component preservation** | `_largest_component` → `_significant_components` — keep all components ≥ min_area, not just biggest | Rotterdam Turtles was losing 2 of 3 turtles (64-68% biggest's size). Now preserves all sister loops while still filtering pin markers (~100px). |

### Documented negative results

| Attempt | What was tried | Why it didn't work |
|---|---|---|
| **Options 1+2** (denser waypoints + k-shortest-paths Fréchet rerank) | Denser waypoint sampling + reranking K candidate Dijkstra paths by shape against the projected cartoon segment | Earlier "fidelity 0.19→0.45 lift" was RANSAC randomness. With seed pinned, all 5 sweep cells produced identical fidelity. At city-graph waypoint scales, `shortest_simple_paths` returns one path per segment — nothing to rerank. |
| **Option 4** (OCR anchors as Dijkstra via-points) | Pin each RANSAC-inlier GCP's OSM node as a hard via in the snap, forcing the path through OCR-identified intersections in order | Nominatim returns one point per street; the cartoon crosses that street at a different point along its length. Pinning forces detours away from the natural crossing. #584 elephant fid 0.190→0.162; #53 Regent's fid 0.365→0.185 (much worse). |

The infrastructure for all 3 attempts is kept in tree behind opt-in CLI flags
(`--mapmatch-k-paths`, `--mapmatch-rerank`, `--via-nodes`) so future refinement
can build on it.

### Visual deliverables

- [`stravart/data/phase4b_diag/verdict_comparison.html`](../../stravart/data/phase4b_diag/verdict_comparison.html) — per-route card layout, 20 routes, embedded thumbnails (Phase 4a 4-panel for street-scale, Phase 4b 3-panel for city-scale), opens via `open` in the default browser. New preference: for image-heavy diagnostics, default to HTML with embedded `<img>` rather than markdown link-to-PNG.
- `phase4b_diag/city_scale_*.png` — 5 OCR0-route diagnostics confirming full-shape city-scale fallback
- `phase4b_diag/skeleton_diag_*.png` — 6 routes showing the 25-75% pre-fix skeleton loss
- `phase4b_diag/sweep_*.json` — RANSAC-seeded sweep data for options 1+2+4

---

## What remains (3 parallel streams for the next session)

The user wants the next session to run **three streams in parallel via subagents** since the file overlap is minimal. Paste-ready prompts:

| Stream | Prompt file | Branch | Files touched |
|---|---|---|---|
| **A — Option 3 (HMM map-matcher)** | [`stravart_phase4c_option3_hmm_prompt.md`](stravart_phase4c_option3_hmm_prompt.md) | `claude/stravart-phase4c-option3-hmm` | `stravart/mapmatch.py`, `stravart/reconstruct.py`, new tests |
| **B — Option 4 refinements** | [`stravart_phase4c_option4_refinements_prompt.md`](stravart_phase4c_option4_refinements_prompt.md) | `claude/stravart-phase4c-option4-refinements` | `stravart/crossref.py`, `stravart/mapmatch.py`, `stravart/reconstruct.py` |
| **C — Dashboard + distance** | [`stravart_phase4c_dashboard_distance_prompt.md`](stravart_phase4c_dashboard_distance_prompt.md) | `claude/stravart-phase4c-dashboard-distance` | `stravart/reconstruct.py` (small), `stravart/data/phase4b_diag/verdict_comparison.html`, new `stravart/data/phase4b_diag/render_*.py` |

**File-overlap check:** All three touch `mapmatch.py` or `reconstruct.py` to some degree, BUT:
- Stream A adds a new function (HMM) and wires it via a knob
- Stream B refines existing `via_nodes` extraction and adds a new helper
- Stream C only adds a tiny `route_distance_m` to `Reconstruction` + edits the HTML report

Risk of merge conflicts is low if each stream uses `git merge origin/main` carefully at the end. If conflicts emerge, they're trivial (additive parameters).

---

## Blockers & open issues

| Item | Status |
|---|---|
| Fundamental Nominatim limitation: one point per street | Diagnosed. Refinement-1 (per-street node enumeration via Overpass) is in Stream B. |
| `torch + numpy 2.x` incompatibility on this dev machine | Worked around with `numpy<2`. Document in next session if reproducing. |
| Multi-polyline thread-through for street-scale snap | Currently only wired through city-scale fallback. OCR-anchored snap still consumes the legacy single longest `polyline`. Possible follow-up after Streams A-C. |
| Full 1654-route batch run | Predicted from curated-20: ~2-5% strict + ~3-8% review + ~30-60% city-scale. Not yet run live. Pending user budget. |

---

## Key decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Default `min_confidence` 0.6 → 0.4 | Adopted | The new gate (min_gcps + min_rmse) rejects garbage *before* the confidence calc, so dropping the post-fit threshold can't accept underdetermined reconstructions. The `review_status` split keeps the strict tier visible. |
| Default `mapmatch_use_via_nodes` (Option 4) | OFF — opt-in via `--via-nodes` | Empirical sweep showed via-pinning to Nominatim centroids hurts fidelity on both #584 and #53. Keep machinery for refinement. |
| Default `mapmatch_k_paths` (Option 2) | 1 — opt-in via `--mapmatch-k-paths` | At city-graph waypoint scales, `shortest_simple_paths` returns one path per segment. Nothing to rerank. |
| Default `waypoint_step_m` (Option 1) | 30 — same as Phase 3 | Denser waypoints (15m) didn't measurably improve fidelity. Keep 30m for batch-runtime efficiency. |
| Multi-polyline contour trace wired into city-scale only | Yes — city-scale path uses `contour.polylines`; street-scale snap still uses `polyline` | Conservative: city-scale GPX output IS the shape, so the full-coverage trace is a clear win. Street-scale's affine fit doesn't depend on contour completeness (only on anchor points), so the lift is uncertain without a live sweep. |
| HTML reports with embedded images for diagnostics | Yes — saved in `feedback_html_visual_reports.md` | User explicitly prefers visual side-by-side over markdown link-to-PNG. Open via `open <path>.html`, not preview panel. |

---

## Files modified

| File | Change |
|---|---|
| `stravart/contour.py` | +`trace_all_polylines`, +`_significant_components`, `RouteContour.polylines`/`total_length_px`/`skeleton_coverage`, kept legacy `trace_route`/`_largest_component` |
| `stravart/centroid_project.py` | NEW — Phase 4b city-scale fallback, accepts flat list OR list-of-polylines |
| `stravart/mapmatch.py` | +`trace_all_polylines` (oops — actually that's contour.py); + k-shortest-paths + Fréchet rerank, + `via_nodes` injection, + diagnostic counters (`reranked_segments`, `via_nodes_pinned`) |
| `stravart/georef.py` | +`kept_gcps` field on `Georectification` (Phase 4b inliers) |
| `stravart/reconstruct.py` | +`_city_scale_fallback`, +`_dedup_gcps_by_geo`, +`_gcp_pixel_hull_frac`, threaded new knobs, `Reconstruction.kind`/`review_status`/`is_runnable` |
| `stravart/reconstruct_pipeline.py` | Threaded knobs, persistence of `kind`/`review_status` columns, city-scale bypasses min_confidence (its conf is capped at 0.5) |
| `stravart/db.py` | Additive: `reconstruction_kind`, `reconstruction_review_status` columns + `update_reconstruction` extended |
| `stravart/cli.py` | New flags: `--strict-threshold`, `--min-gcps`, `--no-city-scale-fallback`, `--mapmatch-k-paths`, `--mapmatch-rerank`, `--via-nodes` |
| `stravart/gpx_export.py` | +`build_gpx_multi_segment` for branching cartoons (city-scale fallback) |
| `stravart/tests/*` | +35 new tests; total 219 pass, all offline |
| `docs/handoffs/stravart_phase4b_tighten_and_fallback.md` | NEW — predecessor handoff (created mid-session) |
| `stravart/data/phase4b_diag/*` | NEW directory — verdict report, sweep results, contour/skeleton diagnostics, city-scale renders |

---

## Branch status

- **`claude/stravart-phase4b-tighten-fallback`** at `a72b87b`, pushed to origin, **no PR** — user makes merge call.
- 7 commits ahead of `origin/claude/stravart-phase4a-poc`; can rebase or merge to `main` when ready.

---

## Memory updates this session

- `feedback_html_visual_reports.md` — new feedback memory for HTML-with-images preference
- `lessons_stravart_fidelity_threshold.md` — updated to reflect the 0.4/0.6 split
- `lessons_stravart_image_zoom_classes.md` — updated to reference the implemented Phase 4b fallback
- `MEMORY.md` index — added HTML visual reports entry

No new lessons promoted to global `~/.claude/lessons.md` — the multi-polyline trace, multi-component preservation, and Nominatim-centroid limitations are all strav.art-specific.

---

## Doc-freshness reverse-lint

Clean. The lessons updated this session were rule-aligned with code; no stale normative guidance flagged in project docs.

---

## Next-session orchestration

When you start the next session, paste this in:

> Pick up strav.art Phase 4c. Read `docs/handoffs/stravart_phase4b_wrap_handoff.md` first, then dispatch 3 parallel subagents on the 3 prompt files in `docs/handoffs/stravart_phase4c_*_prompt.md`. Each prompt is paste-ready, has its own branch, and the file overlap between streams is minimal.

The 3 streams together cover:

1. Cracking the wrong-turn snap problem (Streams A + B race two different approaches)
2. Closing the catalog ship-rate gap (Stream C extends city-scale fallback to `min_gcps`-failed routes too)
3. Polishing the user-facing report (Stream C: distance, dashboard prettify)
