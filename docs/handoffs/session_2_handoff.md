# Session 2 Handoff — GPS art Phase 2: Optuna search + turning-function + grid prescreen + Quick Draw

**Date:** 2026-05-03
**Branch:** `claude/fresh-implementation-plan` (worktree on `claude/compassionate-satoshi-c3cccd`)
**Worktree:** `.claude/worktrees/compassionate-satoshi-c3cccd`
**Commits this session:** `b4af8cf`, `bc969e5`
**PR:** [#3 — Phase 2: Optuna search + turning-function + grid prescreener + Quick Draw](https://github.com/wan-huiyan/DoodleRun/pull/3)

## Completed

- [x] **In-tree turning function** at [prototype/turning_function.py](../../prototype/turning_function.py). Implements Arkin et al. (1991) (~50 LOC NumPy: cumulative-arc-length parameterisation + closed-form rotation optimisation + optional phase shift over starting vertex). Required because PyPI `turning-function` has no Python 3.11+ wheels and no sdist.
- [x] **Fidelity ensemble bumped to 1.00.** [prototype/fidelity.py](../../prototype/fidelity.py) gains `turning_score()`; `combined_score` now blends MHD 0.35 + Fréchet 0.30 + IoU 0.20 + turning 0.15. The `test_default_weights_sum_to_known_total` pin updated.
- [x] **Grid prescreener** at [prototype/grid_prescreener.py](../../prototype/grid_prescreener.py). Three independent diagnostics (`road_density_km`, `grid_regularity`, `is_connected`) + a `prescreen()` combinator returning `(ok, info)`. Density computed directly (osmnx's `basic_stats` requires bbox/area metadata that synthetic test grids don't carry); regularity uses `ox.bearing.orientation_entropy` (folded-bearing variance breaks at the 90→0° fold boundary).
- [x] **Optuna TPE search** in [prototype/route_generator.py](../../prototype/route_generator.py): `generate_search_v2()` with `TPESampler(n_startup_trials=20)`, distance soft-penalty + 2× hard cap, early-stop callback at `score < 0.04`, graph-injection seam for tests. `GeneratedRoute` gains `rotation_deg`, `best_params`, `fidelity_breakdown` fields.
- [x] **Per-candidate graph radius** introduced as `V2_DEFAULT_GRAPH_RADIUS_M = 15_000` (the cap from plan §9). The 30 km figure is now formally the **search** radius (where candidate centres are placed); the per-candidate graph load is 15 km to keep callable-weight Dijkstra tractable.
- [x] **Quick Draw curation** at [tools/quickdraw_to_shape.py](../../tools/quickdraw_to_shape.py). Downloads ndjson, filters recognised single/two-stroke samples, normalises to [-0.5, 0.5]², emits importable Python modules. Aliases `dino → dragon`, `chicken → bird` (those exact categories don't exist in Quick Draw). Five variants per animal under [prototype/quickdraw_variants/](../../prototype/quickdraw_variants/).
- [x] **Multi-variant shape registry** in [prototype/shapes.py](../../prototype/shapes.py): `SHAPE_VARIANTS` exposes `[canonical, *quickdraw]` per animal; `SHAPES` unchanged for legacy callers.
- [x] **Real-world smoke validated on London E14.** [samples/v2_smoke/london_e14_pig.png](../../samples/v2_smoke/london_e14_pig.png) shows the routed polyline tracing real streets around the Isle of Dogs / Greenwich. Distance 80 km / fidelity 0.307 — the high distance is expected for single-shot `generate_v2` (no distance penalty); the visual confirms Phase 1 wiring is real.
- [x] **PNG renderer** at [prototype/render_preview_png.py](../../prototype/render_preview_png.py). Matplotlib + contextily basemap; reuses the macOS keychain CA bundle plumbing.
- [x] **Tests:** 140 prototype + 17 server, all green. New suites: `test_turning_function` (10), `test_grid_prescreener` (12), `test_shapes` (6), and the Phase-2 wing of `test_route_generator` (6).
- [x] **PR opened** at [#3](https://github.com/wan-huiyan/DoodleRun/pull/3).

## Remaining (prioritised)

1. **Perf**: callable-weight Dijkstra is too slow at 15 km (London ~3 min/segment, SF/Manhattan ≥8 min and didn't finish in this session). The fix is one of:
   - Pre-compute per-edge bearings + perpendicular distances once at graph load and store as edge attributes; weight callable becomes O(1) lookups instead of haversine + projection per call. Likely 10-50× speedup.
   - Cap Dijkstra search by snapping to nodes within a small bbox around the current target segment (subgraph view).
   - Switch to `nx.astar_path` with a haversine heuristic (admissible + monotonic for our cost — the C₃ floor is 0).
2. **Optuna search smoke** vs single-shot baseline on the same city. We have wiring (PR #3) and one single-shot baseline (London E14 80 km / 0.307); next step is to run `generate_search_v2(... n_trials=50)` on London once perf allows it, log the score curve, and confirm the soft-penalty pulls distance back into the 15-30 km band.
3. **Phase 3 — Multi-variant search.** [prototype/route_generator.py](../../prototype/route_generator.py)`:generate_search_v2` currently takes a single `outline`. Wrap it in a `generate_search_v2_multi(outline_variants: List[List[Point]])` that runs the Optuna study per variant and returns the best across variants. The pieces are already in place: `SHAPE_VARIANTS` exposes the candidate list per animal.
4. **Phase 4 — Valhalla / FMM A/B.** Plan §5 / §6 Phase 4. Untouched.
5. **Phase 5 — Server + iOS wiring.** Plan §6 Phase 5. Server still imports legacy `generate()` / `generate_search()`; needs `generate_search_v2` + multi-variant + `algorithm` enum on the API model.
6. **Real-world smokes for SF + Manhattan** once perf is in.

## Blockers & Open Issues

- **Perf is the gating issue for Optuna search at scale.** A single trial on a 15 km graph takes ~3-8 minutes wall-clock. With `n_trials=50` that's 2-7 hours per city. Not acceptable for interactive use. Pre-computing edge attributes is the obvious next move; do this BEFORE wiring the search into the server.
- **OSMnx Overpass downloads need the macOS keychain CA bundle on this machine.** [prototype/smoke_v2.py](../../prototype/smoke_v2.py) and [prototype/render_preview_png.py](../../prototype/render_preview_png.py) wire it via env vars at import time. The plan said "no more HTTPS calls for routing" but Overpass is still HTTPS — the keychain workaround stays useful.
- **`generate_search_v2` was tested on a 20×20 synthetic grid** (`test_route_generator.py::TestGenerateSearchV2`); never run end-to-end on a real OSMnx graph this session because of the perf issue above.
- **Quick Draw category aliases.** `dino → dragon`, `chicken → bird`. The plan §3.3 claimed Quick Draw covers all five DoodleRun animals; it doesn't. The aliases are documented in `QD_CATEGORY_ALIASES`.

## Key Decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Use upstream `turning-function` package or write our own? | Wrote our own (~50 LOC NumPy). | PyPI wheels stop at Python 3.10; no sdist; we're on 3.11. The wrapper would be more code than the algorithm. Documented in `prototype/turning_function.py` so the next person can swap to the package once wheels exist. |
| `basic_stats(G)` for road density? | No — direct sum of edge `length` ÷ bbox-area. | `ox.basic_stats` requires bbox/area metadata absent from our synthetic test graphs; the direct calc gives the same answer for the comparison we care about. |
| Folded-bearing variance for grid regularity? | No — `ox.bearing.orientation_entropy`. | `(bearing % 90)` makes 89.999° and 0° appear linearly far apart even though they're perceptually identical (one is just below the fold). Entropy is the canonical fix and is one OSMnx call. |
| Single radius for both search + per-candidate graph? | No — split into `V2_DEFAULT_SEARCH_RADIUS_M = 30_000` and `V2_DEFAULT_GRAPH_RADIUS_M = 15_000`. | Plan §9 risks already capped per-candidate at 15 km; the previous code conflated the two and made smoke runs intractable. |
| Quick Draw aliases for missing categories | `dino → dragon`, `chicken → bird`. | Plan §3.3 promised Quick Draw covers all five; it doesn't. Aliases are explicit + logged so anyone scanning sample outlines knows their source. |
| Smoke against 3 cities? | London only this session; SF + Manhattan logged as Phase-3 follow-up. | Each city smoke is ~3-8 min wall-clock; total exceeded the time budget. London proved the wiring; the rest is repeat verification. |

## Files Modified

| File | Change |
|---|---|
| `prototype/turning_function.py` | NEW (~190 LOC) — Arkin et al. 1991 in NumPy |
| `prototype/grid_prescreener.py` | NEW (~140 LOC) — density, regularity, connectivity |
| `prototype/route_generator.py` | +160 — `generate_search_v2`, `_rotate_xy`, `_distance_adjusted_score`, V2 graph-radius constants |
| `prototype/fidelity.py` | +30 — `turning_score`, weight bump, breakdown gains `turning` |
| `prototype/shapes.py` | +25 — `SHAPE_VARIANTS` + lazy quickdraw loader |
| `prototype/smoke_v2.py` | NEW — three-city real-world smoke runner |
| `prototype/render_preview_png.py` | NEW — matplotlib + contextily PNG renderer |
| `prototype/requirements.txt` | +`optuna>=3.0`; documented why turning-function is in-tree |
| `tools/quickdraw_to_shape.py` | NEW (~200 LOC) — Quick Draw curation pipeline |
| `prototype/quickdraw_variants/{pig,cat,dog,dino,chicken}_quickdraw.py` | NEW — auto-generated, 5 variants each |
| `prototype/tests/conftest.py` | +`make_grid_graph` shared factory |
| `prototype/tests/test_turning_function.py` | NEW (10 tests) |
| `prototype/tests/test_grid_prescreener.py` | NEW (12 tests) |
| `prototype/tests/test_shapes.py` | NEW (6 tests) |
| `prototype/tests/test_route_generator.py` | +6 (TestGenerateSearchV2 + helpers) |
| `prototype/tests/test_fidelity.py` | weight-pin + breakdown set updated for turning |
| `samples/v2_smoke/london_e14_pig.{geojson,png}` | NEW — first real-world routed pig |
| `.gitignore` | +`prototype/cache/`, +`prototype/quickdraw_data/` |

## Branch Status

`claude/fresh-implementation-plan` ahead of `main` by 6 commits (`869c37c..bc969e5`). PR #3 open against `main`.

## Suggested Phase 3 brief (one paragraph for the next session)

> Branch `claude/fresh-implementation-plan` (HEAD `bc969e5`). Read this handoff plus the open PR #3. Two priorities, in order: **(1) edge-attribute pre-compute** to make the W-K Dijkstra fast enough for interactive Optuna search — store per-edge bearing + length once at graph load, reduce the weight callable to O(1) attr lookups; target 10-50× speedup. **(2) multi-variant search wiring** — wrap `generate_search_v2` to iterate over `SHAPE_VARIANTS[name]` and pick the variant + (offset, scale, rotation) combo with the best score. Verify both with a real-graph London + SF smoke under 5 min each. Then Phase 5 (server + iOS wiring) is unblocked.
