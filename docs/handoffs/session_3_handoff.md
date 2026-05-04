# Session 3 Handoff — GPS art Phase 3: Dijkstra perf + multi-variant search + real Optuna smoke

**Date:** 2026-05-03
**Branch:** `claude/fresh-implementation-plan` (worktree on `claude/intelligent-darwin-74f4ab`)
**Worktree:** `.claude/worktrees/intelligent-darwin-74f4ab`
**Commits this session:** `1eaf53d`, `3f5dd4a`, `441a1ce` (pushed onto `claude/fresh-implementation-plan`, on top of session-2 tip `25b2be3`)
**PR:** [#3 — Phase 2 + 3 on the same branch](https://github.com/wan-huiyan/DoodleRun/pull/3) (still open against `main`; 9 commits ahead)

## Completed

- [x] **Profiled the real hot spot.** A single `shape_aware_route` call against the cached London 15 km graph (870 K edges) took 75 s. cProfile showed 71.5 s in `ox.distance.nearest_nodes` (35 anchor snaps × 2 s/each, each rebuilding a GeoDataFrame from scratch), 3.5 s in `bidirectional_dijkstra`, 2.9 s in the W-K weight callable. The session-2 hypothesis that the weight callable was the bottleneck was wrong — it's already cheap.
- [x] **`precompute_graph_attrs(G)`** in [prototype/osmnx_router.py](../../prototype/osmnx_router.py) walks the graph once at load time and stashes:
  (a) a scipy `cKDTree` of node positions in equirectangular metres around the graph centroid, plus the parallel node-id array, on `G.graph["_dr_node_kdtree"]`;
  (b) per-edge midpoint lat/lon and endpoint lat/lon on every parallel edge's inner attr dict.
  Marker flag `G.graph["_dr_precomputed"]` makes it idempotent. `load_graph(precompute=True)` wires this by default; tests using bare `make_grid_graph` opt out implicitly via fallback paths in `nearest_node` / weight callable.
- [x] **`nearest_node_cached` + `nearest_nodes_cached`** use the KDTree directly (single batched scipy query). `shape_aware_route` collapses 35 anchor snaps to one batched query; `nearest_node` falls back to `ox.distance.nearest_nodes` when precompute hasn't run, so the existing test suite keeps using uncached graphs without changes.
- [x] **`waschk_kruger_cost_fn` refactored**: hoists the per-segment local-tangent constants out of the per-edge hot path, inlines haversine and point-to-segment projection, and reads precomputed `_dr_v_lat / _dr_mid_lat / _dr_mid_lon` off the inner edge dict when available. Same numerical answer; ~30 % less time per `weight()` call.
- [x] **Re-profile**: 75 s → **2.2 s** (34× speedup), beating the 10–50× target. Profile breakdown after fix: 2.2 s `bidirectional_dijkstra` + weight, 0 s nearest_nodes (precomputed once at load).
- [x] **`generate_search_v2_multi`** in [prototype/route_generator.py](../../prototype/route_generator.py): runs an independent Optuna study per outline variant against a single shared graph (avoids the precompute cost per variant), tags `variant_index` into `best_params` of the winning route, prescreens once across the multi-call, skips per-variant exceptions instead of propagating, raises only when *all* variants fail.
- [x] **Parameterised search bounds** on both `generate_search_v2` and the multi wrapper:
    `scale_factor_min` / `scale_factor_max` — narrows the TPE search space
    `hard_cap_factor` — promotes the previously hard-coded 2.0 × cap
    `soft_penalty_weight` — promotes the previously hard-coded 0.3
  Defaults preserve prior behaviour.
- [x] **Tests +13** (`TestPrecomputeGraphAttrs`, `TestNearestNodeCached`, `TestCostFunctionUsesPrecomputedAttrs`, `TestGenerateSearchV2Multi`). **170 passing** (153 prototype + 17 server).
- [x] **Real-graph smoke** in [prototype/smoke_v2.py](../../prototype/smoke_v2.py) — 30 trials × 2 variants per city, scale ∈ [0.5, 1.3], hard-cap 1.5×:
    - **London E14**: 19.10 km / score **0.2937** / **166 s** — canonical pig variant (better than Phase-1 baseline 0.307)
    - **SF Sunset**: 13.08 km / score **0.2953** / **126 s** — quickdraw exemplar (variant 1)
  Both under the 5 min/city budget; both score below the Phase-1 baseline. London inside [14, 26] km soft band; SF 5 % below the lower end (the search picked a smaller-scale quickdraw variant whose turning score is 0.28 vs canonical 1.0 — a worthwhile fidelity-for-distance trade).
- [x] **Preview PNGs + geojson + summary JSON** committed under [samples/v2_smoke/](../../samples/v2_smoke/):
    - https://github.com/wan-huiyan/DoodleRun/raw/claude/fresh-implementation-plan/samples/v2_smoke/london_e14_pig_search.png
    - https://github.com/wan-huiyan/DoodleRun/raw/claude/fresh-implementation-plan/samples/v2_smoke/sf_sunset_pig_search.png
- [x] **Pushed to `claude/fresh-implementation-plan`** — PR #3 picks up the new commits automatically.

## Phase 3 exit criteria check (per session-3 prompt)

| Criterion | Result |
|---|---|
| 10–50× wall-clock improvement on the per-trial path | ✅ 34× (75 s → 2.2 s) |
| `generate_search_v2_multi` wired and unit-tested | ✅ 5 new tests |
| Smoke for 2 cities completes under 5 min each | ✅ London 2.8 min, SF 2.1 min |
| Distance inside `[0.7×, 1.3×] target_distance_m` | ✅ London 19.1 km. ⚠️ SF 13.1 km (5 % under) |
| Score on London Pig improves vs Phase-2 baseline (combined < 0.307) | ✅ 0.2937 |
| All tests green | ✅ 170 passing |
| PNGs pushed | ✅ |

## Remaining (prioritised)

1. **Phase 5 — server + iOS wiring (the actual unblock)**. The server still imports the legacy `generate()` / `generate_search()`. Wire `generate_search_v2_multi` behind an `algorithm` enum on the API model so the SwiftUI app can request the new pipeline. Plan §6 Phase 5.
2. **Tune SF distance back into the soft band**. The 13.1 km route lost 5 % to the smaller-scale quickdraw variant. Two options: (a) raise `soft_penalty_weight` from 0.3 → 0.5 globally, (b) widen `scale_factor_min` floor to 0.7 (smaller scales then physically can't produce sub-14 km routes). Either change is a one-liner; pick after a side-by-side visual on the SF PNG.
3. **Manhattan smoke** — was deferred from session 2 and not addressed in session 3. Will need an Overpass download (~60–120 s) for the 15 km graph. Repeat verification only — the wiring is proven on London + SF.
4. **Phase 4 — Valhalla / FMM A/B (plan §5).** Untouched. Less urgent than Phase 5 since Phase 3 produces working road-snapped routes; this is for when we want a second routing engine to A/B test.
5. **Multi-animal smoke** — `SHAPE_VARIANTS` exposes 5 animals × 6 variants each; smoke only covered pig. Worth a one-off run per animal once Phase 5 lands so the iOS app has a curated default per (city, animal) cell.

## Blockers & open issues

- **Turning-function score collapses to 1.0 on canonical pig in London** (despite hausdorff 0.010, IoU 0.51). The W-K router straightens many of the pig's curved features into rectilinear blocks, which the turning-angle metric is most sensitive to. SF quickdraw variant scored 0.28 — the simpler outlines are friendlier to turning fidelity. Worth investigating in Phase 5 whether turning's 0.15 weight is doing useful work or just adding noise.
- **OSMnx Overpass + macOS keychain CA** still required for fresh downloads (SF needed it this session). The `smoke_v2.py` and `render_preview_png.py` env-var dance still works.
- **No Valhalla integration yet.** Plan §5 phase 4. Not blocking Phase 5.

## Key decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Where is the Dijkstra hot spot? | `ox.distance.nearest_nodes`, not the W-K weight callable | cProfile showed 71.5 s of 75 s in nearest_nodes rebuilding a GeoDataFrame per call. The session-2 plan over-indexed on the weight function. |
| Per-call GDF rebuild or cache once? | Cache `cKDTree` + `node_ids` + `(origin_lat, m_per_deg_lon)` on `G.graph` at load | Single scipy tree query per route × 50 trials = 1 build instead of 50×35. Equirectangular metres around the centroid is accurate enough (<0.1 % error in 15 km) for KNN. |
| Stash bearings on edges? | No — only midpoint + endpoint lat/lon | Bearings need a 2nd target-segment-aware term to be useful, and the perpendicular-projection term covers it. Keeps the per-edge attr dict smaller. |
| Single-study multi-variant or per-variant studies? | Per-variant | TPE priors don't transfer across variants (different perimeters → different (offset, scale) Pareto fronts). Per-study is also more parallelisable for a future async server. |
| Promote `hard_cap_factor` to a parameter? | Yes (default 2.0 preserved) | Smoke uses 1.5× to prune wasteful trials faster; production callers can stay on 2.0 if they want a wider exploration window. |

## Files modified / added

| File | Change |
|---|---|
| `prototype/osmnx_router.py` | +200 lines — `precompute_graph_attrs`, `nearest_node[s]_cached`, hoisted/inlined cost function. Old `nearest_node` kept as fallback. |
| `prototype/route_generator.py` | +120 lines — `generate_search_v2_multi`, parameterised search bounds in both v2 entry points. |
| `prototype/smoke_v2.py` | Now drives `generate_search_v2_multi`; tighter scale band; optuna logging WARNING. |
| `prototype/tests/test_osmnx_router.py` | +9 tests across 3 new classes (precompute, cached snap, cost-fn parity). |
| `prototype/tests/test_route_generator.py` | +5 tests in `TestGenerateSearchV2Multi` (variant index, skip-on-fail, raise-on-all-fail, empty list). |
| `samples/v2_smoke/london_e14_pig_search.{geojson,png,html}` | NEW — search-mode London smoke. |
| `samples/v2_smoke/sf_sunset_pig_search.{geojson,png,html}` | NEW — search-mode SF smoke. |
| `samples/v2_smoke/summary_v2_multi.json` | NEW — per-city distance/score/time/breakdown/best_params. |

## Branch status

`claude/fresh-implementation-plan` is now at `441a1ce`, **9 commits ahead of `main`** (Phase 1 + Phase 2 + Phase 3). PR #3 is open and tracks the branch.

## Suggested Phase 4 brief (one paragraph for the next session)

> Branch `claude/fresh-implementation-plan` (HEAD `441a1ce`). Phase 3 is complete: edge-attr precompute + KDTree cache deliver a 34× speedup, `generate_search_v2_multi` works end-to-end, real-graph smoke for London + SF lands under 5 min/city with scores beating the Phase-1 baseline. The next priority is **Phase 5 — server + iOS wiring** (the plan §6 Phase 5 — *not* the §5 Valhalla A/B, which is lower priority): wire `generate_search_v2_multi` into [server/app.py](../../server/app.py) behind an `algorithm` enum on the API request model (so the existing `generate()`/`generate_search()` paths stay as a fallback), update the iOS app's request payload, and keep the fidelity breakdown in the response so the mobile UI can show what it scored. Two side-tasks to fold in: (a) raise `soft_penalty_weight` to 0.5 (or floor `scale_factor_min` at 0.7) to push SF back into the [14, 26] km band, and (b) run a Manhattan smoke now that Overpass downloads work cleanly. Don't touch Valhalla yet.
