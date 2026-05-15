# ADR-0001 — Snap waypoints to DISTINCT OSM graph nodes (cKDTree, k=50)

**Status:** Accepted — 2026-05-15
**Context:** `multi_template/` shape-aware Dijkstra router
**Authors:** Session lead + Claude

## Context

The multi-template router projects an animal-outline template to lat/lon waypoints,
then snaps each waypoint to the nearest OSM graph node before per-leg Dijkstra.
The pre-existing implementation was:

```python
snapped = ox.distance.nearest_nodes(G, lons, lats)
snapped = list(dict.fromkeys(snapped))   # dedupe keeping order
```

At St Albans with scale=6.65 km and `n_waypoints=64`, this silently deduped
**9 of 64 waypoints** onto the same graph node — typically leg-tip waypoints,
because outline waypoints get denser inside thin appendages (legs, trunk).
Affected legs lost their dedicated routing target, so Dijkstra never had to
detour into the leg-tip area and the appendage disappeared from the trace.

The symptom was the v2 user complaint: *"the route doesn't look like an
elephant. they look incomplete."* No error was logged; `len(routed.legs)`
silently dropped to 54 instead of 63.

## Decision

Replace `dict.fromkeys` dedup with a `scipy.spatial.cKDTree` snap that picks
the nearest **unused** graph node per waypoint, querying `k=50` nearest
candidates per waypoint:

```python
node_ids = list(G.nodes)
node_xy = np.array([(G.nodes[n]["x"], G.nodes[n]["y"]) for n in node_ids])
tree = cKDTree(node_xy)
used: set[int] = set()
snapped: list[int] = []
for lat, lon in zip(lats, lons):
    _, idxs = tree.query([lon, lat], k=min(50, len(node_ids)))
    for idx in idxs:
        nid = node_ids[int(idx)]
        if nid not in used:
            used.add(nid); snapped.append(nid); break
    else:
        snapped.append(node_ids[int(idxs[0])])  # all 50 used, fall back
```

This guarantees `len(snapped) == len(waypoints)` (subject to total node count)
so every waypoint contributes a distinct Dijkstra target.

## Consequences

**Positive:**
- Elephant route iou jumped 0.193 → 0.321 (v2 → v3) at St Albans with no other
  changes.
- `n_waypoints=64` at small scale (3-4 km) is now usable; previously deduped
  catastrophically and gave worse results than n_waypoints=32.
- `render_locked.py` now logs a warning if `len(routed.legs) != n_waypoints-1`
  so future regressions surface immediately.

**Negative / costs:**
- Snap step is O(N_waypoints × log N_nodes) via KDTree + O(K) per waypoint;
  measurable but negligible (<50 ms for 64 waypoints on an 80k-node graph).
- KDTree builds once per call — fine because each search candidate already
  rebuilds the graph anyway.
- `k=50` is a heuristic fallback bound. If all 50 nearest nodes are already
  used, we fall back to allowing duplicates (logged but doesn't crash). Have
  not observed this in practice; if it ever fires, the diagnostic warning
  prints the fact.

## Confirmation

- Smoke test passes: `python3 -m multi_template.smoke_test`
- Length assertion passes on the locked routes:
  `python3 -m multi_template.render_locked` (regenerates within 100 m).
- Per-leg diagnostic at `multi_template/previews/diagnostic/DIAG_*.png` shows
  all 63 legs present for both locked locations.

## Notes

This is a **silent failure mode** in the previous code — no error message,
no warning, just visibly missing legs in the rendered output. The lesson
generalizes: any `nearest_node` snap on a dense graph where multiple
waypoints can land within road-grid spacing needs distinct-node enforcement.
Captured in skill `gps-art-splice-loop-template-routing` v1.1.0 step 2b.

## References

- Commit `f7df239` — v3 elephant lock
- `multi_template/router.py:120-145` (the new snap block)
- Project memory `lessons_elephant_lockin_config.md` — v3 update section
