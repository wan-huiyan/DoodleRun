# strav.art Phase 4c — Stream C: city-scale fallback extension + dashboard + distance

**Branch:** `claude/stravart-phase4c-dashboard-distance` (from `claude/stravart-phase4b-tighten-fallback`)
**Predecessor handoff:** `docs/handoffs/stravart_phase4b_wrap_handoff.md`
**Parallel session:** A (option 3 HMM) and B (option 4 refinements).
**File overlap:** `stravart/reconstruct.py` (small additions) — A and B touch it too but for different concerns (knobs, not output fields). `stravart/data/phase4b_diag/verdict_comparison.html` (this stream owns it). No conflict expected.

## Three independent sub-tasks

This stream bundles three small, high-leverage improvements. None depend
on each other. Build them in this order:

### C1. Extend city-scale fallback to fire when `min_gcps` fails

**Problem.** 5 of the 7 "honestly rejected" routes in the curated 20 (#60
Hampstead, #942 London Bear, #577 Dumbo Cambridge, #1272 St Albans Shark,
#1294 Whale in Wales) have:
- Working contour extraction (the cartoon shape is captured)
- Working title-derived geocoding (the city is known)
- BUT only 3-4 OCR'd streets — fails `min_gcps=5`, fails the affine fit, hard-fails

The city-scale fallback already handles OCR0 routes by placing the contour
at the title centroid at fixed scale. Extend it to ALSO fire when the
affine fit fails for low GCP count, as long as we have a title-derived
lat/lon. Output: same `kind="city-scale"`, `review_status="review"`,
`is_runnable=False`.

**Implementation.**

In `stravart/reconstruct.py`, the current control flow is:
1. OCR0 with title_latlon → `_city_scale_fallback` (already there)
2. OCR finds streets → affine fit → snap → maybe ship

Add a third branch: if step 2 fails at the `min_gcps` or `min_rmse` gate
AND `title_latlon` is supplied, fall through to `_city_scale_fallback`
instead of hard-failing.

```python
if len(gcps) < min_gcps:
    if title_latlon is not None:
        # Low-anchor fallback — same as OCR0 path
        return _city_scale_fallback(rec, title_latlon=title_latlon, ...)
    rec.failure = f"georef: only {len(gcps)} unique GCPs (need ≥{min_gcps})"
    return rec
```

Same for the post-fit `min_rmse_m` gate.

**Expected impact on the curated 20:**

| route | Current verdict | Phase 4c verdict |
|---|---|---|
| #60 Hampstead | FAIL conf<0.4 | CITY-SCALE |
| #942 London Bear | FAIL conf<0.4 | CITY-SCALE |
| #577 Dumbo Cambridge | FAIL min_gcps(3<5) | CITY-SCALE |
| #1272 St Albans Shark | FAIL min_gcps(4<5) | CITY-SCALE |
| #1294 Whale in Wales | FAIL min_gcps(3<5) | CITY-SCALE |

Catalog with output goes 14/20 → 19/20 in the curated set. The 1 still
hard-failing (#36 West Devon — no title-latlon) is genuinely unrecoverable.

**Tests.** Add tests in `test_reconstruct.py`:
- min_gcps fail + title_latlon → city-scale (new path)
- min_rmse fail + title_latlon → city-scale (new path)
- min_gcps fail + no title_latlon → hard fail (existing path)

### C2. Add route distance to shipped GPX

User asked: "can you put the route total distance on the html, for the
ones you do manage to nail down GPX?"

Currently `Reconstruction.matched.length_m` exists for street-scale routes
(it's the snapped polyline arc length). For city-scale routes, the
projected polyline's arc length is the equivalent.

Add:
- `Reconstruction.total_distance_m: float | None` — populated for any
  shipped result (street or city-scale). For street-scale: `matched.length_m`.
  For city-scale: compute from `geo_polyline` via haversine sum.
- Persist via `update_reconstruction(..., distance_m=...)` and a new
  `reconstruction_distance_m` column on the `routes` table (additive
  migration in `stravart/db.py`).
- Surface in the HTML verdict report (Stream C3 — they pair naturally).

**Tests.** Add tests in `test_reconstruct.py`:
- Distance populated for street-scale ship
- Distance populated for city-scale ship
- Distance NULL for failures
- DB persistence round-trips

### C3. Dashboard prettify + distance

Improve `stravart/data/phase4b_diag/verdict_comparison.html`:
- Add a **distance column** next to each route's verdict (use the new
  `total_distance_m`; format as "12.4 km" for >1km else "830 m")
- Add a **total ship-tier distance** to the Tallies section ("Strict ship:
  2 routes · 31.6 km total")
- Better visual hierarchy — maybe shift the per-route card layout into a
  full responsive table with sortable columns (using a vanilla JS sort, no
  framework deps — keep it open-via-`open`-friendly)
- Sticky header so the column headers stay visible when scrolling
- Add small KPI tiles at the top (Strict / Review / City-scale / Failed +
  total decorative distance) — design-inspired by route-tracker dashboards

Don't go overboard — the report needs to stay opens-locally-in-Chrome-
without-a-server. No external CSS/JS deps. Inline everything.

Re-render city-scale diagnostics with the new contour fix already
applied (commit 60e8082 in the predecessor) so the HTML matches the
current pipeline output:

```bash
python3 stravart/data/phase4b_diag/render_city_scale.py
```

Open via `open` in the default browser per the user's preference (NOT the
preview panel).

## Done criteria

- [ ] C1: low-anchor + low-RMSE + title-latlon paths fall through to city-scale fallback
- [ ] C1: ~5 new tests in `test_reconstruct.py` covering the new branches
- [ ] C2: `total_distance_m` on `Reconstruction`, persisted to DB via additive migration
- [ ] C2: tests for distance population (street + city-scale + null)
- [ ] C3: distance column added to verdict HTML
- [ ] C3: KPI tiles at top with total distances per tier
- [ ] C3: sortable / sticky-header table
- [ ] HTML opens in browser, visual check passes
- [ ] Commit + push, no PR

## Stream-A / Stream-B coordination

C is independent. After A or B merge, C's diagnostics will re-render with
improved fidelity on review-tier routes (the HTML report will reflect
whatever the snap step produces). No code merge conflicts expected —
C touches `reconstruct.py` only for the city-scale fall-through addition
and the `total_distance_m` field, both of which are additive.

## Files you'll likely touch

- `stravart/reconstruct.py` — extend `_city_scale_fallback` triggers + add `total_distance_m`
- `stravart/db.py` — additive column `reconstruction_distance_m`
- `stravart/reconstruct_pipeline.py` — persist distance
- `stravart/tests/test_reconstruct.py` — new tests for C1 + C2
- `stravart/tests/test_reconstruct_pipeline.py` — DB persistence
- `stravart/data/phase4b_diag/verdict_comparison.html` — major edits for C3
- `stravart/data/phase4b_diag/render_city_scale.py` — re-render diagnostics
