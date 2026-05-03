# DoodleRun — Future Sessions Plan

Living document. Update when sessions complete or scope changes.
Source-of-truth for *algorithm* roadmap is `GPS_ART_IMPLEMENTATION_PLAN.md`.

## Current state (as of Session 1)

- Branch: `claude/fresh-implementation-plan` at `8831993`
- Phase 1 of `GPS_ART_IMPLEMENTATION_PLAN.md`: **DONE**
- Tests: 103 prototype + 17 server, all green
- No PR yet — open at user's discretion

## Phase 2 — Search optimization (next session)

See [docs/handoffs/session_2_prompt.md](../handoffs/session_2_prompt.md) for the full brief.

- [ ] Real-world smoke run on 3 cities (London / SF / Manhattan); visual inspection
- [ ] Add `turning-function`, wire into `combined_score` at weight 0.15; bump weight-sum test to 1.00
- [ ] `prototype/grid_prescreener.py` — road density + grid regularity + connectivity
- [ ] Add `optuna`; `generate_search_v2()` with TPE over (offset_lat, offset_lon, scale, rotation), early stop, prescreener pruning
- [ ] Tests for the search loop with mocked `load_graph`

## Phase 3 — Shape gallery + Quick Draw! (after Phase 2)

- [ ] `tools/quickdraw_to_shape.py` — curate Quick, Draw! ndjson exemplars per animal
- [ ] Multiple variants per animal in `prototype/shapes.py`
- [ ] `generate_search_v2()` tries top-N templates per animal
- [ ] Time-boxed pilot of `liganggis/run_drawing` subgraph approach

## Phase 4 — Map-matching alternative (parallel with Phase 2-3)

- [ ] `prototype/valhalla_client.py` — wrapper for `trace_attributes` (Docker)
- [ ] A/B vs Waschk-Krüger on 5 animals × 5 cities × 3 distances
- [ ] Optional FMM fallback if Valhalla can't tune `gps_accuracy` high enough

## Phase 5 — Server + iOS integration

- [ ] Replace OSRM-backed endpoints in `server/main.py` with `generate_v2`/`generate_search_v2`
- [ ] Update `server/models.py` (algorithm, rotation, template, fidelity_breakdown fields)
- [ ] Mobile SPA: update default distance slider to 15-30 km, add quality toggle
- [ ] iOS app: matching Swift model + UI changes
- [ ] **Delete** legacy `prototype/osrm_client.py`, `generate()`, `generate_search()` once v2 ships
