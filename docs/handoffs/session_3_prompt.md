# Session 3 Prompt — GPS art Phase 3: Dijkstra perf + multi-variant search + real Optuna smoke

**Branch to use:** `claude/fresh-implementation-plan` (current HEAD: `bc969e5`)
**Worktree:** Pick the existing worktree on `claude/fresh-implementation-plan`, or fork into a `claude/*` sibling and push to `claude/fresh-implementation-plan` like sessions 1 and 2 did.

## Key context — what's done

- **Phases 1 + 2** of [GPS_ART_IMPLEMENTATION_PLAN.md](../../GPS_ART_IMPLEMENTATION_PLAN.md) are complete and on the branch.
- Read [docs/handoffs/session_2_handoff.md](session_2_handoff.md) for the full Phase-2 summary.
- The Optuna search (`generate_search_v2`) and grid prescreener and turning-function are wired in and unit-tested against synthetic grids. **No real-graph search smoke yet** because the W-K Dijkstra perf can't sustain `n_trials=50` interactively.
- 140 prototype + 17 server tests green. PR [#3](https://github.com/wan-huiyan/DoodleRun/pull/3) open.

## Files to read first

1. [docs/handoffs/session_2_handoff.md](session_2_handoff.md) — what just shipped + decisions
2. [GPS_ART_IMPLEMENTATION_PLAN.md](../../GPS_ART_IMPLEMENTATION_PLAN.md) — especially §3.6, §6 Phase 3
3. [prototype/osmnx_router.py](../../prototype/osmnx_router.py) — `waschk_kruger_cost_fn` is the perf hot spot
4. [prototype/route_generator.py](../../prototype/route_generator.py) — `generate_search_v2` (just-shipped) and where the multi-variant wrapper goes
5. [prototype/shapes.py](../../prototype/shapes.py) — `SHAPE_VARIANTS` registry the multi-variant search will iterate

## Priority tasks (in order)

### 1. Pre-compute per-edge attributes — make Dijkstra interactive

Today `waschk_kruger_cost_fn` calls haversine + projection per edge per Dijkstra visit. On a 15 km London graph (~250K edges, ~10K visits per shortest_path) × 35 segments per outline × 50 Optuna trials, that's ~440M function calls per generate_search_v2 — minutes-to-hours.

The fix: walk the graph once at load time and stash per-edge primitives (bearing, length, midpoint lat/lon, optionally a precomputed integer "direction bin") on edge attrs. Then the weight callable becomes a constant-time lookup:

```python
def weight(u, v, edge_data):
    inner = _pick_parallel_edge(edge_data)
    return alpha * inner["_v_to_end_m"] + beta * inner["length"] + gamma * _perp_lookup(inner, seg_start, seg_end)
```

Two of the three terms (`v→segment_end` distance, midpoint→segment perpendicular) depend on the *current* target segment so they can't be fully precomputed — but the per-edge half (midpoint coords + length + bearing) can. Aim for 10-50× wall-clock improvement on the per-trial path.

Start with profiling: `python -m cProfile -o smoke.prof prototype/smoke_v2.py` and confirm the hot spot is `_haversine` / `_point_to_segment_distance_m` before refactoring.

**Validation:** `prototype/smoke_v2.py` should complete all 3 cities in under 5 min total (currently 8+ min/city, often timing out).

### 2. Multi-variant search wiring

`SHAPE_VARIANTS[name]` already returns `[canonical, *quickdraw]`. Add `generate_search_v2_multi(outline_variants, ...)` that:
- For each variant, runs an Optuna study (or a *single* study with variant as a categorical hyperparameter — your call; the study-per-variant route is simpler and more parallelisable)
- Picks the (variant, offset, scale, rotation) combo with the best distance-adjusted score
- Returns a `GeneratedRoute` with the variant index in `best_params`

Add `prototype/tests/test_route_generator.py::TestGenerateSearchV2Multi` with the synthetic-grid pattern.

### 3. Real-graph Optuna smoke

Once perf and multi-variant land, run `generate_search_v2_multi(SHAPE_VARIANTS["pig"], 51.5074, -0.0148, n_trials=50)` for London + SF and verify:
- Distance lands inside [0.7×, 1.3×] target_distance_m (the soft-penalty fixes the 80 km blow-up the single-shot `generate_v2` produced last session)
- Best fidelity ≤ Phase-1 baseline (0.307 for London E14)
- Wall-clock under 5 min/city

Save geojson + PNG previews to [samples/v2_smoke/](../../samples/v2_smoke/) named `<city>_<animal>_search.{geojson,png}`. Push them in a separate commit.

## Guardrails

- **Don't lower `V2_DEFAULT_SEARCH_RADIUS_M = 30_000`.** That's the candidate-placement radius (plan §0). Per-candidate graph load uses `V2_DEFAULT_GRAPH_RADIUS_M = 15_000` (already capped per plan §9 risks).
- **Don't reimplement** `nx.shortest_path`, A* heuristics, or Optuna samplers; pre-compute and lookup, don't replace.
- **Don't touch the legacy `generate()` / `generate_search()`** — still the safety net until Phase 5 wires v2 into the server.
- **Don't expand the keychain CA bundle helper to fire by default in unit tests.** It's only loaded by `smoke_v2.py` and `render_preview_png.py` (the only HTTPS-touching scripts). Keep the test suite hermetic.

## Verification before declaring Phase 3 done

- All tests green (`pytest prototype/tests/ server/tests/`)
- Smoke for 2 cities completes under 5 min each with `generate_search_v2_multi`; PNGs pushed
- Score on London Pig improves vs the Phase-2 baseline (combined < 0.307)
- Push to `claude/fresh-implementation-plan`; update PR #3 (or open a follow-up if Phase 3 is large)
- Then call `/session-handoff` with a Session 4 prompt
