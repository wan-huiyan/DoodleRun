# Session 5 Handoff — visually-recognisable pigs + server/iOS wiring

**Branch:** `claude/clever-mcclintock-3f60b3` (pushed; HEAD `1216214`)
**Worktree:** `.claude/worktrees/clever-mcclintock-3f60b3`
**Server running on:** `http://192.168.5.69:8000` (LAN — phone-accessible)

## What happened

Phase 4's brief was "wire the Phase-3 generator into the server + iOS". I did that, but the user opened the existing PNGs and said *"these don't look like pigs."* They were right — Phases 1-3 had built infrastructure on top of a router that produced numerically-good fidelity scores but visually-tangled traces. Most of Session 5 ended up rebuilding the router for visual quality, with the server/iOS wiring running alongside.

## Visual progression on Isle of Dogs (Thames U-bend), 20 km pig

| Iteration | Score | What you see |
|-----------|-------|--------------|
| Phase 3 baseline (London E14) | 0.294 | Tangled blob with heavy crossings |
| St Albans baseline (N=50, no anti-revisit) | 0.465 | Spaghetti |
| + anti-revisit + γ=15 (N=50) | 0.355 | Recognisable animal silhouette but noisy |
| **+ N=15 + VW simplify (final)** | **0.209** | **Clear pig: snout, ear, tail, two legs visible** |

Final PNG: [`samples/v2_iter/isle_of_dogs_pig_iod_n15_big.png`](../../samples/v2_iter/isle_of_dogs_pig_iod_n15_big.png) — committed to the branch.

## Algorithm changes (`prototype/osmnx_router.py`, `prototype/route_generator.py`)

1. **Anti-revisit penalty** in `waschk_kruger_cost_fn`. Each segment's edges go into a `visited_edge_keys` set; the next segment pays `revisit_penalty_m` (default 4000 m) if it tries to reuse them. This is what kills the doubling-back / internal-crossing pattern that made Phase-3 outputs unrecognisable.

2. **Direction-aware C₃** (off by default). Optional bias toward the exterior of the outline via a centroid-side check. We tried `inside_penalty_factor=4` first and it made the route balloon out beyond the outline; the default 1.0 is now no-op, kept as a hook for future work.

3. **γ raised 4 → 15.** With anti-revisit on, Dijkstra needs much stronger pull to the segment line; otherwise the cheap-length term wins and the route takes shortcuts.

4. **Default `n_waypoints` 35 → 15.** This was the biggest visual win. Fewer outline anchors → bolder, simpler strokes that read as a pig at a glance. The user's read on the N=50 IoD output was *"too many twists, not recognisable"*; N=15 fixes that. Below 12 the pig features (ear, second leg) collapse — verified at [`samples/v2_iter/_pig_low_n.png`](../../samples/v2_iter/_pig_low_n.png).

5. **Visvalingam-Whyatt simplification (80 m tol)** baked into `generate_search_v2` so the polyline returned to callers is already clean. Drops road-network noise vertices that the user can't tell apart from intentional features. Implemented in `_simplify_polyline_vw`; uses the `simplification` package that was already in `requirements.txt`.

## Server (`server/main.py`, `server/models.py`, `server/static/app.html`)

- New `algorithm: "v2_multi" | "legacy"` enum on `/generate` (default `v2_multi`). v2 path calls `route_generator.generate_search_v2_multi`; legacy path keeps the Phase-1 OSRM iterate-on-scale generator callable for fallback.
- Response gains: `score`, `score_breakdown` (Hausdorff/Frechet/area_iou/turning + weights), `variant_index`, `best_params`, `polyline` (lat,lon alias of geojson), `algorithm` echo.
- 422 if `algorithm=v2_multi` and `distance_km` is outside the 15–30 km band (instead of leaking the prototype's `ValueError` as a 500).
- SPA: distance slider 5..25 → 5..30, default 20 km, algorithm radio, score badge in summary panel.

## iOS (`ios/DoodleRun`)

- `RouteAlgorithm` enum + segmented Picker. Default `v2_multi`.
- Response gains `score` / `scoreBreakdown` / `variantIndex` / `algorithm` — surfaced as a "(Optuna v2)" badge + score line + variant tag in the result row. Distance slider 15..30.
- URLSession timeout 60 s → 300 s. v2_multi takes 2-3 min on a fresh city; the default would race the Optuna search. Pass a custom `URLSession` to override in tests.

## Tests

- 153 prototype + 25 server = **178 tests green**.
- New `TestGenerateV2Multi` class (8 tests) exercises the v2 path: default-algorithm dispatch, explicit algorithm, distance-band validation, variant pass-through, search-failure → 502, etc. v2 stub patches `route_generator.generate_search_v2_multi` so tests stay offline.
- `test_passes_through_route_metrics` updated to pass `simplify_tol_m=0.0` — the synthetic 1.6 km test route would collapse to 2 points if VW-simplified at 80 m.

## Smoke targets (reduced to England-only)

`prototype/smoke_v2.py` `CITIES`:
- `st_albans` — user's home base
- `milton_keynes` — designed grid
- `hemel` — suburban-radial
- `isle_of_dogs` — **Thames U-bend; produces the best pig (fidelity 0.21)**
- `barnes_bend` — Thames bend west
- `richmond` — Thames + park paths

SF + Manhattan removed per user instruction (England-only, the user actually runs these IRL).

## Iter harness

`prototype/iter_v2.py` is a single-city iteration harness for tuning. ~2 min per run on a cached graph. Renders both a basemap PNG and a basemap-free "big" PNG — the latter is what we use to visually judge whether the trace looks like the animal. The original `render_preview_png.py` basemap eats most of the canvas, which is why earlier sessions couldn't tell the route was bad.

```bash
cd prototype
python iter_v2.py --city isle_of_dogs --animal pig --waypoints 15 --trials 30 --tag iod_n15
```

## Server is running

```
http://192.168.5.69:8000   ← phone-accessible, same Wi-Fi
http://localhost:8000      ← this Mac
```

Background task id `b85s6jvpf`. To restart:

```bash
cd server
DOODLERUN_CA_BUNDLE=keychain DOODLERUN_TRUST_KEYCHAIN=1 \
  python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## Open follow-ups for Phase 6

1. **Real-graph end-to-end through the new `algorithm: "v2_multi"` path on London (cached)** — never actually hit the live `/generate` endpoint via the SPA. Recommend doing this first thing next session: open `http://192.168.5.69:8000` on a phone, pick Isle of Dogs (51.50, -0.02), 20 km, hit Generate, confirm the routed polyline matches `samples/v2_iter/isle_of_dogs_pig_iod_n15_big.png`.

2. **Re-run `smoke_v2.py` end-to-end** with the new defaults across all 6 England cities. Expected: most produce a fidelity ≤ 0.30 pig at 20 km. The original Phase-3 smoke summary at `samples/v2_smoke/summary_v2_multi.json` is now stale; rebuild it.

3. **iOS app real-device build** — I updated the SwiftUI source but didn't open Xcode. The base URL hardcode in `RouteService.swift` is `http://localhost:8000`; that doesn't work from a physical iPhone — the user has to either edit it to the LAN IP or expose `baseURL` as a setting. Easiest: read from `UserDefaults` with `localhost:8000` as fallback.

4. **The legacy path is still alive.** `algorithm="legacy"` calls the OSRM generator, which depends on a public OSRM endpoint. With the v2 path producing recognisable pigs, the legacy path is probably ready for deletion in Phase 6 — but only after the v2 smoke confirms quality.

5. **Other animals.** I only verified pig visually. Cat/dog/dino/chicken outlines exist; should run a smoke pass to check whether N=15 is the right default for them too. Animals with more features (chicken's tail feathers, dog's floppy ear) might need N=18-20.

6. **Direction-aware C₃ unfinished.** The hook is in but disabled (`inside_penalty_factor=1.0`). Worth revisiting if anyone wants to push fidelity below 0.20 — the failure mode then is "outline ballooning", which suggests a *milder* version of this penalty (factor 1.5-2.0) might help.

## Decisions worth knowing

- **The fidelity score is rotation-invariant** (turning function). Optuna will pick whatever rotation scores best, which means the user might see a pig facing any direction on their map. We considered constraining rotation but the search would lose flexibility. The right UX answer is: render the route + outline overlay so the user can see what the pig orientation is.
- **Thames bends matter more than grid density.** Isle of Dogs (fidelity 0.21) beats Milton Keynes (0.39) and St Albans (0.42) for pig recognisability. River curves give the outline natural support that grid roads can't. User insight, validated empirically.
- **Visual quality > numeric score.** A 0.355 fidelity at IoD with N=50 looks worse to a human than the same 0.355 at IoD with N=15 (which actually scored 0.21). The score doesn't measure "does this look like a pig" — it measures point-distance. Turning function helps but not enough. Future work: a recognition-aware metric.
