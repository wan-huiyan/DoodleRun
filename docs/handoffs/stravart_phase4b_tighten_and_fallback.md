# strav.art Phase 4b — Tighten gate + city-scale fallback

**Branch:** `claude/stravart-phase4b-tighten-fallback` (off `claude/stravart-phase4a-poc`)
**Status:** ✅ Code + tests landed; no live re-run of the curated 20 (no API
budget burned). Predicted ship rates validated by paper-trace against the
existing run #2 numbers — see §3.
**Date:** 2026-05-15

---

## TL;DR

Phase 4a's run #2 surfaced two distinct failure shapes:

1. **Underdetermined georef** (3–4 GCPs, RMSE=0.0 m, contour projection
   wanders off the cartoon — e.g. #1272 St Albans Shark).
2. **OCR-zero regional zoom** (50% of the curated set — image labels are
   neighbourhood names, no streets parseable — e.g. #208 Berlin Mutt).

Phase 4b tightens the gate against (1) and adds a decorative fallback for (2).
The catalog now distinguishes:

| `kind`         | `review_status` | iOS behaviour                              |
|----------------|-----------------|---------------------------------------------|
| `street`       | `shipped`       | Runnable GPX, no review needed              |
| `street`       | `review`        | Runnable GPX, requires manual approval      |
| `city-scale`   | `review`        | Decorative card; NOT a navigable route      |

Predicted impact on the Phase 4a curated 20 (paper-trace):

| | run #2 baseline | Phase 4b |
|---|---:|---:|
| shipped (strict) | 2/20 (10%) | 2/20 (10%) |
| review tier      | 0          | 2/20 (10%) — Regent's Park, Elephant |
| city-scale       | 0          | 10/20 (50%) — every OCR0 route |
| **catalog with output** | 2/20 (10%) | **14/20 (70%)** |
| genuine garbage rejected | 5/20 still in CONF tier | 5/20 hard-failed at the new gate |

---

## 1. The new gate

`stravart/reconstruct.py` — three additive checks before the affine fit:

### `min_gcps = 5`

3-GCP fits are exactly determined; RMSE is trivially zero regardless of
correctness. The PoC data shows the 3- and 4-GCP fits *always* produce
garbage extrapolation. 5+ GCPs with real Nominatim anchors produce
non-trivial RMSE → meaningful residual → trustable fit.

```python
if len(gcps) < min_gcps:
    rec.failure = f"georef: only {len(gcps)} unique GCPs (need ≥{min_gcps})"
```

### `min_gcp_hull_frac = 0.05`

Convex-hull area of the GCP pixel locations as a fraction of image area.
Rejects "5 anchors all on one street block" — the fit looks great locally
but extrapolation drift scales with the inverse of the coverage fraction.

**Status:** prophylactic. No PoC failure hit this gate specifically (the
PoC's degenerate cases failed `min_gcps` or `min_rmse` first), but
defensive coverage matters at catalog scale.

### `min_rmse_m = 0.5`

After the fit, reject when ≥4 over-determined anchors produce RMSE < 0.5 m.
Real Nominatim hits never fit an affine exactly; RMSE < 0.5 m means
near-collinear or duplicate-node GCPs (e.g. multiple OCR'd labels both
resolving to the same intersection node).

Also added: `_dedup_gcps_by_geo()` collapses GCPs whose geographic
positions are within 5 m of each other into a single anchor (highest
OCR-confidence wins).

---

## 2. The city-scale fallback (`stravart/centroid_project.py`)

New module. When the OCR finds zero parseable street candidates AND
Phase 1's title geocoder placed the row in a city, the orchestrator
falls back to:

1. Find the contour bbox centre in pixels.
2. Place that centre at the city centroid.
3. Scale isotropically so the contour spans `target_width_m` (default 4 km).
4. Apply local equirectangular projection to lat/lon (correctly handles
   latitude-dependent dlon).

Output:
* `kind = "city-scale"`
* `review_status = "review"` (never `"shipped"`)
* `confidence = clamp(title_geocode_confidence, 0.1, 0.5)`
* `is_runnable == False`
* GPX is still written — the iOS client filters on `kind` / `review_status`.

The fallback **skips** the entire OSM stack: no crossref, no graph
download, no map-match. There's no street to snap to.

### Known limitation
The fallback fires only on the OCR0 path. Routes that find streets but
fail crossref (#1333 Paris GPS Drawing) stay hard failures.

---

## 3. Paper-trace validation against run #2

| route | GCPs | RMSE m | new gate verdict | matches run #2? |
|---|---:|---:|---|---|
| 910 London Marathon | 5 | 5.5 | ships, `street/shipped` (conf 0.60) | ✓ unchanged |
| 921 Hackney Horse | 6 | 5.4 | ships, `street/shipped` (conf 0.62) | ✓ unchanged |
| 53 Regent's Park | 6 | 12.7 | **review**, `street/review` (conf 0.58) | ✓ now in review tier |
| 584 Elephant UK | 5 | 2.5 | **review**, `street/review` (conf 0.50) | ✓ now in review tier |
| 60 Hampstead | 5 | **0.0** | FAIL @ min_rmse | ✓ correctly killed |
| 942 London Bear | 5 | **0.0** | FAIL @ min_rmse | ✓ correctly killed |
| 1272 St Albans Shark | **4** | 0.0 | FAIL @ min_gcps | ✓ correctly killed |
| 1294 Whale Wales | **3** | 0.0 | FAIL @ min_gcps | ✓ correctly killed |
| 577 Dumbo Cambridge | **3** | 0.0 | FAIL @ min_gcps | ✓ correctly killed |
| 1333 Paris GPS | — | — | crossref fail (unchanged) | known gap §2 |
| 5, 30, 36, 208, 248, 799, 800, 1135, 1359, 1565 | — | — | **city-scale**, `city-scale/review` | ✓ all 10 OCR0 routes |

Strict-ship rate is unchanged (the 2 marathons). The review tier picks up
the 2 borderline-real reconstructions whose panel-4 PNGs confirm the
projected/snapped polylines overlap (see Phase 4a results §5). The 10
OCR0 regional-zoom routes now produce decorative city-scale cards
instead of dropping entirely. **Genuine garbage** (#60, #942, #1272,
#1294, #577 — heavily cartoonised animals with 3–5 GCPs and RMSE=0) is
killed by the new gate rather than slipping into the review tier.

---

## 4. Knobs

`reconstruct.reconstruct()` and CLI flags (`python3 -m stravart.cli reconstruct`):

| Knob | Default | Tradeoff |
|---|---:|---|
| `min_gcps` | 5 | Below this, georef fit is rejected. 3-4 produce extrapolation garbage. |
| `min_gcp_hull_frac` | 0.05 | Min convex-hull area of GCP pixels / image area. |
| `min_rmse_m` | 0.5 | Anti-degeneracy floor. Real-data RMSE on ≥4 anchors is always > 0. |
| `min_confidence` | **0.4** (was 0.6) | Below: no GPX. Above: GPX is written; tier set by `strict_threshold`. |
| `strict_threshold` | 0.6 | At/above: `review_status='shipped'`. Below: `'review'`. |
| `title_latlon` | None | When set, OCR-zero images fall back to city-scale. |
| `title_confidence` | 0.5 | Passed through to city-scale confidence (clamped 0.1-0.5). |
| `centroid_target_width_m` | 4000 | Bbox width of city-scale contour, in metres. |

---

## 5. Default change: `min_confidence` 0.6 → 0.4

Phase 3's default of 0.6 made the bulk-run ship rate 0/0 for non-marathon
routes. Phase 4b's default is 0.4 because:

1. The new gate (min_gcps + min_rmse) rejects garbage *before* the
   confidence calculation, so dropping the post-fit threshold can't
   accept underdetermined reconstructions.
2. The `review_status` split keeps the strict tier visible — consumers
   who want only `shipped` keep the old behaviour by filtering on
   `review_status = 'shipped'`.

**Consumer guidance** (no current consumer exists, but for future
server/iOS work):

```sql
-- Runnable, no review needed:
WHERE reconstruction_review_status = 'shipped' AND reconstruction_kind = 'street'

-- Runnable but flag for manual approval:
WHERE reconstruction_review_status = 'review'  AND reconstruction_kind = 'street'

-- Decorative card only:
WHERE reconstruction_kind = 'city-scale'
```

`server/` and `stravart.search` do NOT currently consume `gpx_path`, so
this change is safe at merge time. Wire-in plan for whichever surface
adopts the catalog: branch the result rendering on `kind`.

---

## 6. Files touched

```
stravart/reconstruct.py            # new gate + city-scale branch + kind/review_status
stravart/centroid_project.py       # NEW — Phase 4b fallback
stravart/reconstruct_pipeline.py   # passes title_latlon + persists new fields
stravart/db.py                     # 2 new columns (additive migration)
stravart/cli.py                    # 4 new flags
stravart/tests/test_reconstruct.py        # +15 tests
stravart/tests/test_centroid_project.py   # NEW — 8 tests
stravart/tests/test_reconstruct_pipeline.py # +4 tests
```

**196 tests pass total** (178 from Phase 3/4a + 18 new). Offline; no
network. Runtime ~12 s.

---

## 7. What's next

* **Run the full 1,654-route batch** with the new gate. Predicted catalog
  ship rate: strict ~2-5%, review ~3-8%, city-scale ~30-60% (the catalog
  is dominated by stylised art; Phase 4a-style title classification
  found ~5% race-class titles).
* **Wire the iOS client / server endpoint to filter by `kind` and
  `review_status`** — see §5.
* **Phase 4c** (deferred): split the four confidence sub-scores
  (anchor / RMSE / OCR / fidelity) into separate columns and let the
  iOS client surface them rather than the collapsed `confidence`.
* **Crossref fallback** (1/20 of curated set, #1333 Paris) — when OCR
  finds streets but crossref can't cluster, try the title-derived city
  as a hint to bias the cluster search. Small lift, but closes the
  last failure category.
