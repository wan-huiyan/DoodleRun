# Session 2 Prompt — GPS art Phase 2: Optuna search + turning-function + grid prescreen

**Branch to use:** `claude/fresh-implementation-plan` (current HEAD: `8831993`)
**Worktree:** the user is already in one for this branch family — confirm `git worktree list` and pick the worktree on `claude/fresh-implementation-plan` (the main checkout) OR continue in a `claude/*` sibling worktree and push to `claude/fresh-implementation-plan` as Session 1 did.

## Key context — what's done

- **Phase 1 of [GPS_ART_IMPLEMENTATION_PLAN.md](../../GPS_ART_IMPLEMENTATION_PLAN.md) is complete** (commits `dee0663` plan + `8831993` code, pushed).
- The Waschk-Krüger shape-aware Dijkstra runs on a local OSMnx walking graph in [prototype/osmnx_router.py](../../prototype/osmnx_router.py). `generate_v2()` in [prototype/route_generator.py](../../prototype/route_generator.py) wires it together. Defaults: 20 km target distance, 30 km graph radius, 35 waypoints. Out-of-band inputs raise `ValueError`.
- Fidelity ensemble in [prototype/fidelity.py](../../prototype/fidelity.py) currently combines Hausdorff + Fréchet + buffered area-IoU at weights 0.35 / 0.30 / 0.20. Turning function is reserved at weight 0.15 (`DEFAULT_WEIGHTS["turning"] = 0.0` placeholder). **The weight-sum pin test (`test_default_weights_sum_to_known_total`) will fail when you bump turning to 0.15 — update that test to expect 1.00 in the same commit.**
- Tests: 103 prototype + 17 server, all green. Synthetic NetworkX grids only — no live OSM in CI. **First Phase-2 task should include a real-world smoke run.**
- Read [docs/handoffs/session_1_handoff.md](session_1_handoff.md) and [docs/decisions/0001-osmnx-replaces-osrm.md](../decisions/0001-osmnx-replaces-osrm.md) for rationale.

## Files to read first

1. [GPS_ART_IMPLEMENTATION_PLAN.md](../../GPS_ART_IMPLEMENTATION_PLAN.md) — especially §0, §3.4-3.6, §6 Phase 2
2. [prototype/osmnx_router.py](../../prototype/osmnx_router.py) — current router surface
3. [prototype/route_generator.py](../../prototype/route_generator.py) `generate_v2` — the function you'll wrap with the search
4. `dsleo/stravart/optimizers.py` (clone the repo to `~/code/stravart` for reference; **do not fork**) — lift the Optuna TPE pattern
5. [prototype/fidelity.py](../../prototype/fidelity.py) `combined_score` — where to plug the turning-function term

## Priority tasks (in order)

### 1. Real-world smoke run (do this first — it's the missing Phase-1 verification)

Before any new code, run `generate_v2` against three real cities and inspect the output. This forces a real `osmnx.graph_from_point` download, validates the disk cache, and gives you a baseline fidelity number to beat in Phase 2.

```python
# Suggested smoke script — put it at prototype/smoke_v2.py (gitignore later if scratch).
from route_generator import generate_v2
from shapes import SHAPES
import json

cities = [
    ("London-E14",   51.5074, -0.0148),
    ("SF-Sunset",    37.7559, -122.4828),
    ("Manhattan",    40.7831, -73.9712),
]
for name, lat, lon in cities:
    r = generate_v2(SHAPES["pig"], lat, lon, target_distance_m=20_000)
    print(f"{name}: distance={r.distance_m/1000:.2f} km  fidelity={r.fidelity:.4f}")
    # Optionally dump to GeoJSON / KML using existing exporters in prototype/.
```

Expected: each city downloads a graph (~10-60 s first time, instant on rerun), `generate_v2` returns a polyline. **Visually inspect** the result via the existing `visualize.py` or a Folium dump. If it's still spaghetti, the W-K weights (`alpha=1.0, beta=0.5, gamma=4.0`) need tuning before Optuna can help.

### 2. Add turning-function to the ensemble

```bash
.venv/bin/pip install turning-function
```

In [prototype/fidelity.py](../../prototype/fidelity.py):
- Import `turning_function` (verify the API — it may be `from turning_function import distance` or similar; confirm by reading the package after install)
- Subsample both polylines to ≤100 points (lib has a soft cap per plan §3.4)
- Add `turning_score(idealized, snapped)` returning a normalized [0,1] value
- Bump `DEFAULT_WEIGHTS["turning"] = 0.15`; update `combined_score` to include it
- **Update [prototype/tests/test_fidelity.py](../../prototype/tests/test_fidelity.py) `test_default_weights_sum_to_known_total` to expect 1.00 (currently 0.85)**

### 3. Grid prescreener

Create [prototype/grid_prescreener.py](../../prototype/grid_prescreener.py):
- `road_density_km(G)` via `ox.basic_stats(G)`
- `grid_regularity(G)` via `ox.bearing.add_edge_bearings(G)` + bearing-variance
- `is_connected(G, min_fraction=0.7)` — largest weakly-connected component covers ≥70% of nodes
- `prescreen(G) -> bool` — combine all three, return False to skip the candidate

Add a unit test using the synthetic grid from [prototype/tests/test_osmnx_router.py](../../prototype/tests/test_osmnx_router.py) (factor `_grid_graph` into a shared fixture if convenient).

### 4. Optuna-driven search

```bash
.venv/bin/pip install optuna
```

Add `generate_search_v2()` to [prototype/route_generator.py](../../prototype/route_generator.py):
- TPE sampler with `n_startup_trials=20`
- Search space: `offset_lat`, `offset_lon` in ±0.15°; `scale` log-uniform 0.5-3.0; `rotation_deg` 0-360 *(or drop rotation if turning-function is in the ensemble — see plan §3.4)*
- Objective: project outline + run `shape_aware_route` + `combined_score`. Reject candidates failing the prescreen with `optuna.TrialPruned`.
- Hard cap: `target_distance_m * 2.0` returns `inf`; soft penalty `0.3 * |distance_err| / target_distance_m`
- Early stop when score < 0.04 (use `study.stop()` from a callback)
- Default `n_trials=100`, `timeout_s=120`
- Cache the loaded graph **once** at the top of `generate_search_v2` and pass it to every trial — the disk cache covers the first call but in-memory reuse is much faster

### 5. Tests

Mock `osmnx_router.load_graph` in the new search tests to return the synthetic grid (same pattern as `TestGenerateV2Pipeline`). Verify:
- The objective is called `n_trials` times when no early stop fires
- An obviously-bad trial (e.g., outline projected into NYC when grid is in SF) is pruned by the prescreener
- `best_params` are recorded on the returned `GeneratedRoute`

## Guardrails

- **Never lower `DEFAULT_RADIUS_M = 30_000` or the `[15_000, 30_000]` distance bounds.** They're enforced in code and pinned by tests for a reason. If you genuinely need to override for an experiment, do it via a test-only patch — don't change the constants.
- **Don't reimplement what a library owns.** Plan §0 has the tool ownership matrix. If you find yourself writing your own TPE sampler / Fréchet implementation / sym-diff geometry, stop and grep PyPI first.
- **Don't touch the legacy `generate()` / `generate_search()`** — they're the safety net until Phase 5 wires `generate_v2` into the server.

## Verification before declaring Phase 2 done

- All tests green (`pytest prototype/tests/ server/tests/`)
- Smoke run against 3 cities completes; visual inspection on at least one city shows the route hugs the outline (not spaghetti)
- `combined_score` weights sum to 1.00 with the test updated
- Push to `claude/fresh-implementation-plan` and open a PR (`gh pr create --title "Phase 2: Optuna search + turning-function + grid prescreen"`)
- Then call `/session-handoff` with a Session 3 prompt
