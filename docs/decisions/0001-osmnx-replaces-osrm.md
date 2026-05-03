---
status: Accepted
date: 2026-05-03
deciders: Session 1
---

# ADR 0001 — Replace OSRM HTTP routing with local OSMnx + Waschk-Krüger Dijkstra

## Status

Accepted (Session 1, commit `8831993`).

## Context

The pre-Session-1 route generator (`prototype/route_generator.generate*`) sent
all 40 outline waypoints to the public OSRM demo server in a single
`/route/v1/foot/` request. Every routed segment is OSRM's *shortest road
path* between consecutive waypoints, which produced spaghetti routes that
never trace the animal outline (see [GPS_ART_IMPLEMENTATION_PLAN.md §1](../../GPS_ART_IMPLEMENTATION_PLAN.md)).

Constraints that made the OSRM path painful even in success cases:

- 1.1 s/request rate limit on the public demo server
- macOS keychain trust dance for SSL inspection (`macos_keychain_bundle()`)
- HTTP failures on shrinking scales when waypoints land in parks / on water
- No way to bake shape fidelity into the routing cost function

## Decision

Replace OSRM-based routing with a **local OSMnx walking graph + segment-by-segment
Dijkstra** whose per-edge cost is the Waschk & Krüger (2019) formula
`α·C₁ + β·C₂ + γ·C₃`, where C₃ penalizes edges that deviate from the
current target outline segment.

The implementation lives in [prototype/osmnx_router.py](../../prototype/osmnx_router.py)
and is exposed via [prototype/route_generator.generate_v2()](../../prototype/route_generator.py).

The legacy `generate()` and `generate_search()` (OSRM-based) are retained
as fallbacks until Phase 5 wires `generate_v2` into the FastAPI server
and iOS app. They will be deleted at that point.

## Consequences

**Positive**

- No HTTP round-trips, no rate limit, no SSL trust workaround.
- Shape fidelity baked into routing decisions (the C₃ term), not bolted
  on as a post-hoc score.
- Graph downloads cached to `prototype/graph_cache/<lat>_<lon>_<r>.graphml`
  — the second run for any city is offline and fast.
- We own ~30 LOC of cost-function code; everything else (download,
  parsing, snapping, Dijkstra) is library code from `osmnx` / `networkx`.

**Negative**

- New transitive dependency on `scikit-learn` (osmnx uses it for unprojected
  BallTree nearest-neighbor; not surfaced at import time, only on the first
  `nearest_nodes` call).
- First-time graph download for a city takes ~10-60 s and ~10-100 MB of disk.
- C₃ uses a midpoint-distance approximation rather than a full Riemann sum
  along the edge. For typical city-block edges (<200 m) this is within a
  few % of the integrated value; revisit if Phase 2 visual quality requires it.

## Confirmation

- 103 prototype + 17 server tests green at `8831993`.
- `test_osmnx_router.TestWaschkKrugerCost.test_aligned_edge_is_cheaper_than_perpendicular`
  proves the cost ordering on a synthetic grid.
- Real-world visual confirmation is **deferred to Phase 2** (smoke run on
  three cities + visual inspection).

## Related

- Plan: [GPS_ART_IMPLEMENTATION_PLAN.md](../../GPS_ART_IMPLEMENTATION_PLAN.md) §0, §3.2
- Source paper: Waschk & Krüger (2019), *Computational Visual Media* 5(3):303-310
