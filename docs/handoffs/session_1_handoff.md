# Session 1 Handoff — GPS art Phase 1: OSMnx + W-K + extended fidelity

**Date:** 2026-05-03
**Branch:** `claude/fresh-implementation-plan` (commits also on `claude/jolly-lehmann-7850c5`)
**Worktree:** `.claude/worktrees/jolly-lehmann-7850c5`
**Commits this session:** `dee0663`, `8831993`

## Completed

- [x] **Plan §0 added** to [GPS_ART_IMPLEMENTATION_PLAN.md](../../GPS_ART_IMPLEMENTATION_PLAN.md) — explicit tool-ownership table + per-phase library callouts. Two non-negotiables made explicit: 30 km search radius default, 15-30 km distance default (sweet spot 20 km). Commit `dee0663`.
- [x] **OSMnx-based shape-aware router** at [prototype/osmnx_router.py](../../prototype/osmnx_router.py). Implements Waschk & Krüger (2019) per-edge cost C₃ on top of OSMnx primitives (`graph_from_point` + `save/load_graphml` + `nx.shortest_path` with callable weight). Default 30 km radius hard-pinned via `DEFAULT_RADIUS_M`.
- [x] **Extended fidelity ensemble** in [prototype/fidelity.py](../../prototype/fidelity.py):
  - `frechet_score` via `similaritymeasures.frechet_dist` (order-preserving)
  - `area_iou_score` via shapely `LineString.buffer().symmetric_difference()`
  - `combined_score` weighted ensemble (0.35 / 0.30 / 0.20; 0.15 reserved for Phase 2 turning-function)
  - Critical fix: `_shared_origin` so the two polylines compared use the same Cartesian frame
- [x] **VW polyline simplifier** at `shape_utils.simplify_vw` — Rust-backed `simplification.cutil.simplify_coords_vw` with binary-search threshold tuning to land at requested vertex count ±10%.
- [x] **`generate_v2()`** added to [prototype/route_generator.py](../../prototype/route_generator.py). Defaults: 20 km target distance, 30 km graph radius, 35 waypoints. Rejects out-of-band inputs with a loud `ValueError`.
- [x] **Tests:** 103 prototype + 17 server, **all green**. New tests in:
  - [prototype/tests/test_osmnx_router.py](../../prototype/tests/test_osmnx_router.py) — synthetic NetworkX grid, no live OSM
  - [prototype/tests/test_fidelity.py](../../prototype/tests/test_fidelity.py) — Fréchet, area-IoU (with disjoint geographies), combined breakdown, weight-sum pin
  - [prototype/tests/test_shape_utils.py](../../prototype/tests/test_shape_utils.py) — VW reduces to target ±10%, preserves >95% of perimeter
  - [prototype/tests/test_route_generator.py](../../prototype/tests/test_route_generator.py) — defaults pinned, validation raises, end-to-end pipeline with mocked `load_graph`
- [x] **`.gitignore`** updated to skip `prototype/graph_cache/` (multi-MB GraphML).
- [x] **Pushed** to `origin/claude/fresh-implementation-plan` at `8831993`.

## Remaining (prioritised)

1. **Phase 2 — Search optimization** ([plan §6](../../GPS_ART_IMPLEMENTATION_PLAN.md))
   - Add `optuna>=3.0`, `turning-function>=0.1` to `prototype/requirements.txt`
   - `prototype/grid_prescreener.py` (NEW) — `ox.basic_stats(G)` + `ox.bearing.add_edge_bearings(G)` for road-density / grid-regularity prescreen
   - Wire `turning_function.distance(...)` into `combined_score` (weight 0.15; bumps total to 1.00)
   - `generate_search_v2()` — Optuna `TPESampler(n_startup_trials=20)` over (offset_lat, offset_lon, scale, rotation), pattern lifted from `dsleo/stravart/optimizers.py`. Multi-metric scoring + distance soft penalty + early termination (score < 0.04) + grid prescreen
   - **Real-world smoke test:** generate pig route at three real cities (e.g., London E14, SF Sunset, Manhattan); inspect rendered SVG/PNG visually
2. **Phase 3** — Quick Draw! ndjson curation + multiple variants per animal; pilot `liganggis/run_drawing` subgraph approach (time-boxed 1 day)
3. **Phase 4** — Valhalla `trace_attributes` HTTP wrapper (Docker `ghcr.io/valhalla/valhalla`), A/B vs W-K
4. **Phase 5** — wire `generate_v2` into `server/main.py` + iOS app

## Blockers & Open Issues

- **No live OSMnx integration test in CI.** Tests use a synthetic NetworkX grid; the actual OSM download path (`graph_from_point` → `save_graphml`) is unverified. First Phase-2 run against a real city will exercise it.
- **`scikit-learn` is a hidden OSMnx dependency** for unprojected nearest-neighbor (BallTree). Now in `requirements.txt`. Discovered during test run (osmnx import-time check is silent; the failure surfaced only on first `nearest_nodes` call).
- **Generate-v2 fidelity unmeasured on real graphs.** The synthetic grid tests prove the wiring; they don't prove the W-K cost weights (α=1.0, β=0.5, γ=4.0) produce recognizable shapes. Phase 2 needs a smoke run + visual inspection before claiming the algorithm works.
- **Two branches at the same commit.** `claude/jolly-lehmann-7850c5` (worktree) and `claude/fresh-implementation-plan` (main repo) both point at `8831993`. Phase 2 should keep pushing to `claude/fresh-implementation-plan`.

## Key Decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Replace OSRM HTTP with local OSMnx? | Yes — `generate_v2` only; `generate()` and `generate_search()` retained as legacy fallbacks. | Removes 1.1 s/request rate limit + SSL trust dance + spaghetti routing failure mode (plan §1). |
| Where does the W-K cost function live? | `osmnx_router.waschk_kruger_cost_fn` — a closure over the current segment, returned to `nx.shortest_path(weight=callable)`. | NetworkX accepts callable weight functions natively; no monkey-patching of edge attrs needed. |
| C₃ — Riemann-sum or midpoint? | Midpoint distance from edge to target segment. | For typical city-block edges (<200 m) the midpoint is within a few % of the integrated value; ~10× cheaper. Revisit if Phase 2 visual quality demands it. |
| Frame for area-IoU comparison | Both polylines projected through `_shared_origin` — single tangent plane spanning both bboxes. | Per-polyline projection puts them on top of each other; sym-diff returns ~0.8 instead of ~1.0 on disjoint inputs. Bug caught by `test_disjoint_polylines_score_one`. |
| Default target distance | 20 km, hard-bounded to [15 km, 30 km]. | Plan §0 / §1.4 — empirically routes <15 km can't resolve animal features. |

## Files Modified

| File | Change |
|---|---|
| `GPS_ART_IMPLEMENTATION_PLAN.md` | +126/-36 — added §0 Tool Stack + per-phase library callouts |
| `prototype/osmnx_router.py` | NEW (272 lines) — graph cache + W-K cost + segment-by-segment Dijkstra |
| `prototype/fidelity.py` | +175 — Fréchet, area-IoU, combined_score, _shared_origin, _to_local_xy |
| `prototype/shape_utils.py` | +45 — `simplify_vw` (binary-search VW threshold) |
| `prototype/route_generator.py` | +105 — `generate_v2` + V2_* constants |
| `prototype/requirements.txt` | +osmnx, shapely, simplification, similaritymeasures, scikit-learn, numpy |
| `prototype/tests/test_osmnx_router.py` | NEW (160+ lines) — synthetic grid; geometry, cost ordering, MultiDiGraph attr shapes, end-to-end |
| `prototype/tests/test_fidelity.py` | +65 — Fréchet, IoU, combined, default-weights pin |
| `prototype/tests/test_shape_utils.py` | +40 — VW correctness |
| `prototype/tests/test_route_generator.py` | +110 — defaults, validation, mocked pipeline |
| `.gitignore` | +`prototype/graph_cache/` |

## Branch Status

`claude/fresh-implementation-plan` ahead of `main` by 4 commits (`869c37c..8831993`). Ready for Phase 2 work; no PR opened (per Auto Mode — user can request when ready).
