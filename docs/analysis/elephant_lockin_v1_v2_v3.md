# Analysis — Elephant route lock-in journey, v1 → v2 → v3

**Date:** 2026-05-15
**Branch:** `claude/review-demo-route-yo15w`
**Question:** What changed between three iterations of the locked elephant route,
and which of the changes were the load-bearing fixes vs distractions?

## Summary

Three iterations were required because each lock surfaced a new bug or wrong assumption
at the user-judgment layer. The **decisive** fixes turned out to be:

1. **Drop `revisit_penalty_m` to 0** (v1) — already in the skill `gps-art-splice-loop-template-routing` v1.0.0
2. **`n_waypoints` 32 → 64** (v2) — denser sampling per appendage
3. **Snap waypoints to DISTINCT graph nodes** (v3) — the silent dedup bug was the actual cause of "incomplete" routes
4. **Fix `render_locked.py` to use full template polyline, not waypoint resample** (v3) — perception bug
5. **Scale 3-4 km, not 5+ km** (v3) — required snap fix first

Everything else (anatomy decomposition attempt, beta=12 corridor tightening, template
smoothing, three different templates Q01/Q07/S04) was either a distraction or a
user-preference tweak — not load-bearing.

## What each version did and didn't fix

### v1 (`cc2c94d`) — original splice-loop recipe

- Knobs: `revisit_penalty_m=0`, `beta=6`, `n_waypoints=32`, rotation clipped, length penalty off
- Templates: iconic-QD whitelist (Q01/Q07/Q08/Q15/Q18)
- Result: iou 0.075-0.189; user picked rank-4 (ELE-Q01) over Optuna's rank-1
- **User verdict:** "still not enough"
- **Reason:** at n=32, leg-tip waypoints landed at most 1 per leg; with the original
  router most of those leg waypoints went to a body node anyway because no anti-dedup,
  so legs were partial.

### v2 (`ea5ac53`) — denser waypoints

- Added: `n_waypoints=32 → 64`, switched to ELE-Q07 (clearer legs) at both locations
- Result: iou 0.188-0.193, routes 60-63 km
- **User verdict:** "doesn't look like elephant. they look incomplete."
- **Reason 1:** the snap `list(dict.fromkeys(...))` was silently collapsing 9/64
  waypoints onto the same OSM node at scale 6.65 km — typically leg-tip waypoints.
  `len(routed.legs) = 54`, not the expected 63. Hidden because no warning was logged.
- **Reason 2:** `render_locked.py` was plotting the sparse 64-pt waypoint resample
  as the "template" grey reference, drawing chord-across-appendage straight lines.
  Route looked "incomplete" because the grey reference itself was visibly incomplete.
  `preview.py` did this correctly; `render_locked.py` was the divergent path.

### v3 (`f7df239`) — distinct-node snap + render fix + smaller scale

- Added: cKDTree distinct-node snap, full-polyline grey reference, scale 3-4 km,
  switched to ELE-S04 (user pick from gallery), added Maidenhead/Windsor location
- Result: **iou 0.321 (St Albans) / 0.317 (Maidenhead). Routes 41-47 km.** Legs
  count = 63 of 63 expected at both locations.
- **User verdict:** accepted with one known artifact (small upward spike at
  waypoint 43 — the elephant's ear in the template).

## Things that wasted time and why

### 1. Auto-anatomy decomposition (~1 hour)

Tried three algorithms to detect appendage tips programmatically in the outline:
hull-concavity (with `find_peaks`), pinch-pair (closest-point pairs along arc),
and tip-first (local maxima of perpendicular distance from short-baseline chord).

All three failed on stubby-leg elephant templates:
- Hull-concavity got 12 armpit clusters from splice junctions, not 4 leg gaps.
- Pinch-pair merged 4 legs into 1 super-spike when the belly between legs was near-linear.
- Tip-first found 17 candidates — many were body curves, not true U-turns.

**Lesson:** The outline already encodes anatomy via the splice loops; the router
just needs permission (`revisit_penalty_m=0`) and enough waypoints (n=64) to use it.
Detection layer is unnecessary. Captured in skill v1.1.0 Notes.

### 2. Beta tightening (~30 minutes)

Tried `beta=12` (vs default 6) hoping a tighter per-leg corridor would eliminate
the 2-3 Dijkstra shortcut legs the diagnostic surfaced. Result was mixed:
Maidenhead iou went up (0.317 → 0.367), St Albans went DOWN (0.321 → 0.260)
because St Albans' road grid has gaps in some areas and the tighter corridor forced
worse detours.

**Lesson:** Per-location β tuning is real but not a generic lever. Default β=6,
tighten only if the diagnostic shows long shortcut legs AND iou doesn't drop in
test. Captured in skill v1.1.0 Notes.

### 3. Template smoothing (~30 minutes)

After v3 lock, user reported a back-bump that "looks like a spike coming out of
elephant's back." Added Gaussian-1D smoothing (`templates_loader._smooth_outline`)
in arc-length space with wrap mode, swept sigma=0/1.5/3/5. sigma=3 removed the
ear bump cleanly. But user picked the unsmoothed version (iou 0.32) over the
smoothed one (iou 0.31) — they preferred the fidelity over the cosmetic fix.

**Lesson:** Smoothing capability is good to have (skill v1.1.0 step 2d), but
the user-acceptance gate is iou ≥ 0.30, not "look perfect." Don't aggressively
smooth.

## Diagnostic findings on v3

Per-leg diagnostic at `multi_template/previews/diagnostic/DIAG_*.png`:

| Location | Legs | Mean leg | Suspect legs (>2× mean) |
|---|---|---|---|
| St Albans s04_xs | 63 | 0.75 km | 2 (#12, #48) |
| Maidenhead s04_xs | 63 | 0.66 km | 3 (#20, #39, #50) |

Suspect legs = Dijkstra shortcuts cutting across body instead of tracing template.
Total length contribution of all suspect legs is < 10% of route length so they
don't dominate visually, but they're the most obvious remaining route artifacts.
Fixable with per-location β tuning (above) at the cost of trading St Albans for
Maidenhead.

## Cross-references

- Decision: `docs/decisions/0001-snap-waypoints-to-distinct-graph-nodes.md`
- Skill: `gps-art-splice-loop-template-routing` v1.1.0 (locally authored)
- Locked config: `multi_template/locked_routes.json`
- Sister handoff (different pipeline, similar bug): commit `60e8082` on
  `claude/stravart-phase4b-tighten-fallback` — *"trace ALL skeleton edges
  (was: 25-67% lost)"* — same "incomplete drawing" complaint with a
  different root cause (skeleton-trace dropping branches at junctions vs.
  router snap-dedup dropping waypoints). The Phase 4b fix (`trace_all_polylines` +
  multi-trkseg GPX) would be the right approach if we ever need branching
  output instead of one continuous loop here.
