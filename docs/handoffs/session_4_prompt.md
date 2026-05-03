# Session 4 Prompt — GPS art Phase 5: server + iOS wiring of `generate_search_v2_multi`

**Branch to use:** `claude/fresh-implementation-plan` (current HEAD: `441a1ce`)
**Worktree:** Pick the existing worktree on `claude/fresh-implementation-plan`, or fork into a `claude/*` sibling and push to `claude/fresh-implementation-plan` like sessions 1–3 did.

## Key context — what's done

- **Phases 1, 2, 3** of [GPS_ART_IMPLEMENTATION_PLAN.md](../../GPS_ART_IMPLEMENTATION_PLAN.md) are complete and on the branch.
- Read [docs/handoffs/session_3_handoff.md](session_3_handoff.md) for the Phase-3 summary.
- The W-K router is now interactive at scale: 75 s → 2.2 s per route via cached node KDTree + per-edge midpoint precompute. `generate_search_v2_multi` runs ~30 trials × 2 variants per city in 2–3 min on the cached London / fresh-downloaded SF graph. 170 prototype + server tests green. PR [#3](https://github.com/wan-huiyan/DoodleRun/pull/3) open.

## Files to read first

1. [docs/handoffs/session_3_handoff.md](session_3_handoff.md) — what just shipped + decisions
2. [GPS_ART_IMPLEMENTATION_PLAN.md](../../GPS_ART_IMPLEMENTATION_PLAN.md) — especially §6 Phase 5 (server + iOS) and §0 (defaults)
3. [server/app.py](../../server/app.py) — current FastAPI wiring; still imports legacy `generate()` / `generate_search()`
4. [server/tests/](../../server/tests/) — existing 17 tests; the new endpoint variant must not break them
5. [ios/DoodleRun/](../../ios/DoodleRun) — SwiftUI app; the request payload + response schema lives here
6. [prototype/route_generator.py](../../prototype/route_generator.py) — `generate_search_v2_multi` and the parameterised bounds
7. [samples/v2_smoke/summary_v2_multi.json](../../samples/v2_smoke/summary_v2_multi.json) — gold reference for what a v2-multi response looks like

## Priority tasks (in order)

### 1. Add `algorithm` enum on the server API model

Today the server only knows about the legacy generator. Wire `generate_search_v2_multi` behind an `algorithm: Literal["legacy", "v2_multi"]` field on the request schema (default `"v2_multi"` so the iOS app picks up the new path automatically). Keep the legacy path callable for a transition window — Phase 5 is about routing the iOS request, not deleting code.

Response schema additions:
- `score` (float; the distance-adjusted Optuna best)
- `score_breakdown` (`{hausdorff, frechet, area_iou, turning, weights}`)
- `variant_index` (int)
- `best_params` (the offset/scale/rotation tuple that won)
- `distance_m`, `polyline`, `waypoints` already exist; keep their shape unchanged.

### 2. Server unit tests

The 17 existing tests cover the legacy path; add a parallel suite for `v2_multi`. Patch `prototype.route_generator.generate_search_v2_multi` with a stub that returns a canned `GeneratedRoute` so the server tests don't touch OSMnx or run Optuna — that's the pattern the legacy tests already use for OSRM.

### 3. iOS payload + response wiring

Add `algorithm` to the request payload, surface the new fields in `GenerateRouteResponse`, and show `score` in the result panel. The existing UI already shows distance; just append the score and an "(Optuna v2)" badge so it's clear which generator ran.

### 4. Two carry-overs from Phase 3

- **SF distance shortfall**: pump `soft_penalty_weight` from 0.3 → 0.5, OR floor `scale_factor_min` at 0.7. Test by re-running the SF smoke and verifying distance lands in `[14, 26]` km. One-line change either way.
- **Manhattan smoke**: not addressed in session 3. Add a Manhattan entry to `CITIES` in [prototype/smoke_v2.py](../../prototype/smoke_v2.py) and run end-to-end (Overpass download will fire; the keychain CA bundle wiring is already in place).

## Guardrails

- **Don't touch Phase 4 / Valhalla / FMM.** Plan §5 explicitly defers that until Phase 5 (server) is done.
- **Don't lower `V2_DEFAULT_SEARCH_RADIUS_M = 30_000`.** That's the candidate-placement radius (plan §0). Per-candidate graph load uses `V2_DEFAULT_GRAPH_RADIUS_M = 15_000` (plan §9 cap).
- **Don't reimplement** OSMnx primitives, Optuna samplers, or the W-K cost. Phase 3 made them fast; Phase 5 is just about *invoking* them from the server.
- **Don't delete the legacy `generate()` / `generate_search()` paths yet** — they're still the fallback for the `algorithm: "legacy"` enum value. Promotion to a single-path codebase is a separate cleanup phase.
- **Don't run real OSMnx downloads in server unit tests** — patch `generate_search_v2_multi` like the legacy tests patch `route_through`.

## Verification before declaring Phase 5 done

- All tests green (`pytest prototype/tests/ server/tests/`) including new server tests for the v2 path
- iOS build succeeds and a manual smoke produces a routed pig with the new score badge
- One real-graph end-to-end through the new `algorithm: "v2_multi"` path on London (cached) — visual matches the [samples/v2_smoke/london_e14_pig_search.png](../../samples/v2_smoke/london_e14_pig_search.png) the prototype produces directly
- Push to `claude/fresh-implementation-plan`; update PR #3 (or open a follow-up if Phase 5 is large)
- Then call `/session-handoff` with a Session 5 prompt
