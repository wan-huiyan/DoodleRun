# strav.art Phase 4d — Multi-polyline stitched-walk snap (design)

**Date:** 2026-05-15
**Predecessors:** `stravart_phase4b_wrap_handoff.md`, Phase 4c Streams A/B/C
**Status:** Design spec — paste-ready for execution as a single stream
**Suggested branch:** `claude/stravart-phase4d-stitched-walk` (from `claude/stravart-phase4b-tighten-fallback`)

---

## Motivation

The Phase 4b multi-polyline contour trace decomposes the cartoon skeleton into **all** its node-to-node edges (trunk, legs, tail, ears, body — every branch as a separate polyline). This fix shipped on the **city-scale fallback** path, but the **street-scale snap** path (the one that determines what "ship" routes look like) still consumes only the legacy `rec.contour.polyline` — the **single longest path** through the skeleton.

Net effect for branching cartoons:

- **#910 London Marathon** (currently strict-ship fid 0.60): snaps **6.4 km of the cartoon's ~42 km route** — ~⅙ coverage. The runner sees a fragment of the marathon path; the rest of the cartoon is silently dropped.
- **Manchester Dog, Munich Lion, Berlin Mutt, Rotterdam Turtles** (review/ship tier): same posture — only the longest spine traces, branches dropped.
- **All "ship" routes with branches**: visually look incomplete in the `projected vs. snapped` diagnostic. The exported GPX matches what the diagnostic shows.

City-scale also currently ships **multi-segment GPX** (one `<trkseg>` per skeleton branch with pen-lifts between them) — that's a Phase 4b implementation shortcut, not a design decision. A runner can't actually run a multi-segment track without GPS-pausing between segments.

**Phase 4d unifies both code paths around a single stitched-walk algorithm.** Multi-polyline contour decomposition → Chinese-Postman-style Eulerian walk → single continuous projected polyline → snap (per-route auto-pick between Dijkstra and HMM) → single-segment GPX. The runner gets one continuous track for both city-scale and street-scale tiers.

---

## Design decisions (locked)

| # | Decision | Pick | Rationale |
|---|---|---|---|
| 1 | Multi-segment GPX vs. stitched single walk | **Stitched single walk** (Chinese-Postman / Eulerian) | One continuous runnable track. Unifies city-scale and street-scale paths. `build_gpx_multi_segment` deprecated in favor of `build_gpx`. |
| 2 | Fidelity scoring on stitched output | **Fréchet on stitched walk vs. stitched snap** (no dedup) | Fidelity measures what the runner actually runs, including doubled appendages. Prevents gaming by adding meaningless backtracks. |
| 3 | Snap engine | **Per-route auto-pick: Dijkstra + HMM, ship higher fidelity** | Stream A's HMM helped #584 (+23%) but hurt #53 (-34%). Per-route choice exploits both engines' strengths. ~2× snap cost; user accepts. |
| 4 | `is_runnable` on stitched city-scale | **Flip to `True`** | Stitched city-scale produces a real continuous track on real streets. Placement is title-centroid (coarse), but the cartoon shape is genuinely runnable. |
| 5 | Eulerization edge weight | **Projected meter length** | Minimizes added run distance from doubled appendages. W1/W2 equivalent under uniform affine scale; W2 is the runner-honest semantic. |
| 6 | Auto-pick tie-break + failure fallback | **Dijkstra wins ties within 5%; legacy single-polyline as soft-fail** | Cheap, stable engine wins toss-ups. Routes the new pipeline can't snap fall back to Phase 4a-style single-spine "review" tier instead of hard-failing. |

---

## The algorithm

```
contour.trace_all_polylines(skeleton)   # already exists (Phase 4b)
        │
        ▼
build MultiGraph: nodes = skeleton joints, edges = polylines
        │
        ▼
networkx.eulerize(G, weight=projected_meter_length)
   ↳ duplicates min-weight edges to make all node degrees even
   ↳ each duplicated edge represents a backtrack
        │
        ▼
networkx.eulerian_circuit(G_eulerized)
   ↳ ordered iterator over edges (polylines) covering every edge
        │
        ▼
stitch polylines in walk order
   ↳ orient each by shared endpoint with predecessor
   ↳ concatenate pixel coords → single continuous reference polyline
        │
        ▼
georef.project_polyline(reference) → geo_polyline (lat/lon)
        │
        ▼
map_match(geo_polyline, mode="auto")          # NEW auto mode
   ├─ run Dijkstra snap → fidelity_d
   ├─ run HMM   snap    → fidelity_h
   └─ pick by:
       if max(d,h) < threshold AND legacy_single_spine available:
           fall back to legacy spine (kind="review", review_status="soft-fail-fallback")
       elif fidelity_h > fidelity_d * 1.05:   HMM wins
       else:                                  Dijkstra wins (tie → Dijkstra)
        │
        ▼
build_gpx(snapped_polyline)   # single <trkseg>, runnable in Strava
```

---

## New module: `stravart/walk.py`

Houses the stitching layer. Public surface:

```python
def stitch_skeleton_walk(
    polylines: list[list[tuple[float, float]]],
    *,
    weight_fn: Callable[[list[tuple[float, float]]], float] = pixel_length,
) -> StitchedWalk:
    """Compute an Eulerian walk over the skeleton's polyline edges.

    Returns ordered coords (pixel space), the walk's edge sequence, and
    diagnostics (n_edges, n_duplicated_edges, total_walk_length_px).

    Raises ValueError if the skeleton graph is disconnected (no walk
    exists). Callers handle by falling back to the largest connected
    component or to the legacy single-polyline trace.
    """

@dataclass
class StitchedWalk:
    coords: list[tuple[float, float]]   # pixel-space polyline (concatenated)
    edges: list[tuple[int, int]]        # walk sequence in graph-edge space
    n_unique_edges: int
    n_duplicated_edges: int
    total_length_px: float
```

The weight function is parameterized so callers can swap pixel-length (pre-georef) for meter-length (post-georef). Default = pixel-length (works without georef; W2 callers pass `weight_fn=meter_length(rec.georectification)`).

---

## Changes to existing modules

### `stravart/contour.py`
- Mark `RouteContour.polyline` (legacy single-longest) as kept for fallback only
- New helper `polyline_meter_length(poly, georectification)` used as eulerize weight

### `stravart/georef.py`
- No changes — `project_polyline` already accepts any polyline

### `stravart/mapmatch.py`
- New `mapmatch_mode="auto"`: runs both Dijkstra and HMM in sequence, returns the snap with higher fidelity (with the 5% Dijkstra tie-break rule)
- Existing `mapmatch_mode="dijkstra"` / `"hmm"` / `"fmm"` knobs (from Stream A) untouched and remain opt-in singletons

### `stravart/reconstruct.py`
- Both branches (`_city_scale_fallback` and the main street-scale path) call `walk.stitch_skeleton_walk(rec.contour.polylines, weight_fn=meter_length(rec.georectification))` before projecting
- `_city_scale_fallback`: drop `build_gpx_multi_segment`; use `build_gpx` on the stitched single polyline
- `_city_scale_fallback`: flip `is_runnable=True` on success
- New diagnostics field `rec.diagnostics["walk_n_duplicated_edges"]` for transparency
- New soft-fail path: if `walk.stitch_skeleton_walk` raises (disconnected skeleton) OR if both Dijkstra/HMM snaps yield fidelity below `min_confidence`, fall back to legacy single-polyline trace and tag `review_status="soft-fail-fallback"`

### `stravart/reconstruct_pipeline.py`
- Thread `mapmatch_mode` (now defaults to `"auto"`)
- Persist `walk_n_duplicated_edges` and the chosen `snap_engine_used` for the dashboard

### `stravart/db.py`
- Additive: `walk_duplicated_edges INTEGER`, `snap_engine_used TEXT` columns
- Migration is additive — existing rows get NULL

### `stravart/cli.py`
- New default: `--mapmatch-mode auto`
- `--mapmatch-mode dijkstra` / `hmm` / `fmm` remain available for forcing one engine

### `stravart/gpx_export.py`
- Mark `build_gpx_multi_segment` as deprecated — kept for the soft-fail fallback path only (where a disconnected skeleton's largest component still uses the old multi-segment emit)

---

## Tests (target: 245+ passing, up from 227)

### `stravart/tests/test_walk.py` (new — ~12 tests)
- Trivial loop (3 edges forming a triangle) → walk has 3 edges, 0 duplicated
- Single-stick branch (loop + one stick) → walk has 4 edges, 1 duplicated (the stick traversed twice)
- Elephant-like fixture (body + trunk + 4 legs + tail) → walk has 6 + 5 = 11 edges, 5 duplicated (each appendage doubled)
- Disconnected skeleton → raises `ValueError`
- Weight function: pixel-length vs. meter-length give same order under uniform scale
- Edge orientation: stitched coords are continuous (each edge's start matches predecessor's end within ε)
- `StitchedWalk.total_length_px` matches sum of polyline lengths (with doubling)

### `stravart/tests/test_mapmatch.py` (extended — ~4 new tests)
- `mode="auto"` with Dijkstra fid 0.5, HMM fid 0.6 → returns HMM result
- `mode="auto"` with Dijkstra fid 0.5, HMM fid 0.52 (within 5%) → returns Dijkstra result (tie-break)
- `mode="auto"` with both below threshold → returns special `MapMatchResult.fallback_to_legacy=True`
- `mode="auto"` HMM crash → returns Dijkstra result gracefully

### `stravart/tests/test_reconstruct.py` (extended — ~6 new tests)
- City-scale stitched success: `kind="city-scale"`, `is_runnable=True`, single-segment GPX
- City-scale disconnected skeleton: falls back to multi-segment (current behavior)
- Street-scale stitched success: doubled appendages reflected in `total_distance_m`
- Soft-fail fallback: stitched snap fails, legacy single-spine ships with `review_status="soft-fail-fallback"`
- Auto-pick engine selection persisted to `snap_engine_used`

---

## Validation on the curated 20

Run the standard sweep + dashboard re-render after implementation:

```bash
python3 stravart/data/phase4b_diag/render_verdict_html.py  # rebuilds verdict_comparison.html
python3 stravart/data/phase4b_diag/sweep_options.py 910    # London Marathon — expected biggest lift
python3 stravart/data/phase4b_diag/sweep_options.py 584    # Elephant — branching beneficiary
python3 stravart/data/phase4b_diag/sweep_options.py 53     # Regent's — sanity check (low-branch)
```

Expected outcomes:

| Route | Pre-4d coverage | Pre-4d fidelity | Predicted post-4d | Confidence |
|---|---|---|---|---|
| **#910 London Marathon** | ~⅙ (single-spine) | 0.60 (strict) | Coverage closer to full route. Fidelity may dip slightly because doubled segments contribute Fréchet penalty. Strict tier should hold. | High |
| **#921 Hackney Horse** | Single-spine | 0.62 (strict) | All legs + body traced. Strict tier holds. | High |
| **#584 Travelling Elephant** | Single-spine | 0.190 (review) | Trunk + legs + body + ears traced. Fidelity may not lift — wrong-turn problem is orthogonal. Visual coverage dramatically better. | Medium |
| **#53 Regent's Park** | Single-spine | 0.359 (review) | Single closed loop — no doubled edges. Should be identical to Phase 4a. | High (no-op) |
| **City-scale 9 routes** | Multi-segment | n/a | Single-segment runnable GPX. `is_runnable=True`. Visual identical, runner experience much better. | High |

**Headline metric to track:** "% of skeleton coverage in shipped GPX." Pre-4d: longest single path ≈ 30–70% on branching cartoons. Post-4d: should hit 90–100% (the 10% gap is soft-fail fallback routes).

---

## Out of scope for Phase 4d

- **HMM `mode="auto"` performance optimization.** ~3-4 min/route × 1654 = ~100 hours batch. Phase 4e territory: pre-screen via Dijkstra fidelity, only run HMM on routes where Dijkstra fid < strict_threshold.
- **Per-segment soft-fail (partial route ships, partial fails).** Currently: whole route ships or whole route soft-fails. Per-segment shipping adds complexity not justified by curated-20 results.
- **Chinese-Postman optimal ordering for runner UX.** Right now the start node of the Eulerian circuit is whatever `networkx` picks (arbitrary). For runner UX, starting at the most prominent OCR'd intersection might be nicer — but this is purely cosmetic, defer.
- **GPX waypoint annotations** ("Start of trunk", "Tail tip") — design-quality polish, not pipeline correctness.

---

## File-modification summary

| File | Action | LOC delta (est.) |
|---|---|---|
| `stravart/walk.py` | NEW | +250 |
| `stravart/tests/test_walk.py` | NEW | +200 |
| `stravart/mapmatch.py` | Add `mode="auto"` dispatch | +60 |
| `stravart/tests/test_mapmatch.py` | New auto-mode tests | +80 |
| `stravart/reconstruct.py` | Wire stitched walk into both code paths; soft-fail | +100 / -30 |
| `stravart/tests/test_reconstruct.py` | New tests for stitched + auto + fallback | +120 |
| `stravart/reconstruct_pipeline.py` | Thread `mode="auto"` default + persist new fields | +20 |
| `stravart/db.py` | Additive migration | +15 |
| `stravart/cli.py` | New `--mapmatch-mode auto` default | +5 / -3 |
| `stravart/gpx_export.py` | Deprecate multi-segment helper (kept for soft-fail) | +5 |
| `stravart/data/phase4b_diag/render_verdict_html.py` | Add coverage column + engine column | +30 |
| **Total** | | **~+880 LOC, ~33 LOC removed** |

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| HMM 2× snap cost makes batch infeasible | Medium | High | Phase 4e: pre-screen via Dijkstra, only HMM on review-tier candidates. Phase 4d retains `--mapmatch-mode dijkstra` for batch mode. |
| Disconnected skeleton (orphan polyline) breaks walk | Low | Medium | Walk raises `ValueError`; soft-fail to legacy single-spine. Tested. |
| Eulerization picks "ugly" doubling (e.g. duplicates the spine instead of an appendage) | Low | Low | W2 weight (projected meters) ensures min-cost doubling. Worst case: marginally longer run distance. Visible in dashboard `walk_duplicated_edges` column. |
| Auto-pick fidelity scoring isn't a reliable engine selector | Medium | Medium | Tie-break favors stable Dijkstra. Edge cases (HMM scores higher despite visibly worse path) flagged in dashboard for manual review. |
| Strava silently treats single-segment GPX with backtracks as "loop" detection issue | Low | Low | Test on Strava with #584 elephant before flipping `is_runnable=True` default. |
| `is_runnable=True` on stitched city-scale misleads users about placement accuracy | Medium | Medium | City-scale placement is still title-centroid (coarse) — the cartoon is rendered at "approximately this city" not "exactly this address". Surface `kind="city-scale"` prominently in the dashboard + GPX metadata so users know the shape is trustworthy but the geographic placement is not. |
| Fidelity numbers regress on no-branch routes | Very low | n/a | #53 (closed loop, no doubling) should be byte-identical pre/post. Sanity test. |

---

## Done criteria

- [ ] `stravart/walk.py` exists with `stitch_skeleton_walk` + ≥12 tests
- [ ] `mapmatch_mode="auto"` works, default in pipeline + CLI
- [ ] Both `_city_scale_fallback` and the main snap path consume `rec.contour.polylines` (stitched), not `rec.contour.polyline` (legacy)
- [ ] `is_runnable=True` for stitched city-scale; soft-fail fallback retains `False`
- [ ] DB migration additive: `walk_duplicated_edges`, `snap_engine_used` columns
- [ ] 245+ tests pass
- [ ] Live sweep on #910 (London Marathon), #584 (elephant), #53 (Regent's), and 2 city-scale routes shows expected behavior per the table above
- [ ] Dashboard re-rendered with coverage column + engine column
- [ ] Visual sanity-check #584 elephant in Strava: track is continuous, doubled appendages don't break the route
- [ ] Commit + push to `claude/stravart-phase4d-stitched-walk`; **no PR** — user holds merge call

---

## Execution-ready prompt (for the next session)

> Execute strav.art Phase 4d per `docs/handoffs/stravart_phase4d_design.md`. Single-stream work; create branch `claude/stravart-phase4d-stitched-walk` from `claude/stravart-phase4b-tighten-fallback`. Implement `stravart/walk.py` first (with tests, TDD), then wire `mapmatch_mode="auto"`, then thread the stitched walk through both city-scale and street-scale paths. Validate on curated-20 routes #910, #584, #53, plus 2 city-scale routes. Update the dashboard. Commit + push, no PR — user holds merge call.

---

## Open questions for next session

None — all design choices are locked. Implementation can proceed end-to-end without further user input.
