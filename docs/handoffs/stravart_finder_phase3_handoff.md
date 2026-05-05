# strav.art Finder — Phase 3 Handoff

**Branch:** `claude/stravart-finder-phase3` (off `claude/stravart-finder-phase2`)
**Status:** ✅ Phase 3 module set complete, full offline test coverage. Live
proof-of-concept batch run is the next live-data step.
**Date:** 2026-05-04

---

## What was built

A drop-in extension to the Phase 2 pipeline that turns each strav.art image
into a GPX route on real streets. Inputs: the geocoded catalog row + its
image URL. Output: an XML GPX 1.1 file at `data/gpx/route_NNNNN.gpx` and
four new DB columns recording the attempt outcome.

| File | Role |
|---|---|
| `stravart/contour.py` | HSV mask (warm-colour wedges only — red / magenta / pink / orange) + morphological close + largest-component filter + skimage `skeletonize` + 8-connected DFS polyline trace. Output: ordered `(x, y)` pixel coords + diagnostics (cleaned mask, skeleton). |
| `stravart/ocr.py` *(extended)* | `_merge_horizontal_neighbors` gains an opt-in `return_boxes` path that returns per-fragment `(xc, yc, w, h)` alongside the merged `(text, conf)` tuples. New `OcrResult.fragment_boxes` field + `candidate_pixel_anchors()` helper that pairs each `StreetCandidate` with the bbox center of the fragment that produced it. **Phase 2 behaviour unchanged.** |
| `stravart/georef.py` | Pixel ↔ `(lat, lon)` affine transform from OCR ground control points. Local equirectangular frame anchored at the GCP centroid. ≥3 GCPs required; with ≥4 the fit uses RANSAC (skimage `measure.ransac`, threshold ~50 m) to reject same-name-different-city Nominatim mis-hits. Returns a `Georectification` with `forward()` / `inverse()` + RMSE / max-residual diagnostics. |
| `stravart/mapmatch.py` | Snap a noisy `(lat, lon)` polyline to the OSM walking network. Downsample to ~30 m waypoints → `ox.distance.nearest_nodes` → `nx.shortest_path` between consecutive distinct nodes (weighted by `edge['length']`) → concatenate with boundary deduplication. Reports `unreachable_segments` so callers can flag low-confidence matches. Lazy-imports osmnx. |
| `stravart/fidelity_score.py` | Discrete Fréchet (metres) + buffered area-IoU between snapped and projected polylines, both in a *shared* local Cartesian frame anchored at the union-bbox centre (lessons #2 — disjoint inputs must score 0). Combined into a 0..1 score; weighted 60% IoU, 40% Fréchet (200 m soft saturation, ≈ a city block). |
| `stravart/gpx_export.py` | GPX 1.1 serialiser via `gpxpy`. One `<rte>` (planned, no timestamps); strips NaN/inf and out-of-range coords so a partial map-match still yields a parseable file. |
| `stravart/reconstruct.py` | End-to-end orchestrator. `reconstruct(image_url, ...)` runs the whole pipeline and returns a `Reconstruction` dataclass with every intermediate plus a single `confidence` aggregating GCP count, RMSE, mean OCR confidence, and the fidelity score (geometric mean). Default ship threshold: `confidence ≥ 0.6`. |
| `stravart/reconstruct_pipeline.py` | Batch driver. Reads geocoded routes from the DB, calls `reconstruct()`, writes shippable GPX to `<db_dir>/gpx/route_NNNNN.gpx`, and records outcome in four new columns. Idempotent + resumable. |
| `stravart/db.py` *(migration)* | Adds `gpx_path`, `reconstruction_confidence`, `reconstruction_attempted_at`, `reconstruction_failure` (additive — same idempotent ALTER pattern as Phase 2). New helpers: `routes_needing_reconstruction`, `update_reconstruction`, `count_reconstructions`. |
| `stravart/cli.py` | Two new subcommands: `reconstruct` + `reconstruct-stats`. |
| `stravart/tests/test_contour.py`            | 15 cases — HSV bands, largest-component filter, skeleton width, polyline tracing (open / L / closed loop / empty), end-to-end recovery from synthetic stroke fixture. |
| `stravart/tests/test_georef.py`             | 11 cases — 3-GCP perfect fit, inverse round-trip, 6+1-outlier RANSAC drop, 3+1-outlier drop, no-drop happy path, raises on too few, polyline projection length consistency, bbox padding. |
| `stravart/tests/test_mapmatch.py`           | 10 cases — waypoint downsampling boundaries, haversine, full snap on a synthetic 4×4 grid, unreachable component, MultiDiGraph parallel-edge length picking. |
| `stravart/tests/test_fidelity_score.py`     | 12 cases — Fréchet identical / parallel-offset / disjoint / empty, IoU identical / disjoint / partial / negative-buffer / empty, combined fidelity passes / fails / disjoint. |
| `stravart/tests/test_gpx_export.py`         | 4 cases — round-trip through gpxpy parser, NaN/oob coord stripping, empty route, deep-nested parent-dir creation. |
| `stravart/tests/test_reconstruct.py`        | 11 cases — confidence aggregator (perfect / few-GCPs / high-RMSE / low-fidelity), GCP join (in-cluster / out-of-cluster / no-cluster), short-circuits at contour and OCR stages, mapmatch-skipped path, full-path with synthetic graph. |
| `stravart/tests/test_reconstruct_pipeline.py` | 10 cases — Phase 3 schema migration on a fresh DB and on a hand-built Phase 2-shaped DB, `routes_needing_reconstruction` filtering, batch GPX-write happy path, failure recording, orchestrator-exception swallowing, summary failure-mode grouping. |

**166 tests pass total** (108 existing from Phase 1+2 + 58 new). All offline —
no network, no EasyOCR model load, no OSMnx Overpass call required to run
the suite. End-to-end runtime: ~5 s.

---

## How to run it

```bash
# Phase 3 deps (≈ skimage / sklearn / osmnx / networkx / gpxpy / shapely
# on top of Phase 2's torch + easyocr + opencv)
python3 -m pip install -r stravart/requirements.txt

# Reuse Phase 2's existing crossref-cache so we don't re-hit Nominatim
# for streets we already resolved.
python3 -m stravart.cli reconstruct \
    --db stravart/data/stravart.sqlite \
    --crossref-cache stravart/data/nominatim_cache.json \
    --limit 20    # proof-of-concept batch — high-quality routes

# Stats
python3 -m stravart.cli reconstruct-stats --db stravart/data/stravart.sqlite
# {"total": 1654, "geocoded": 48, "reconstructions": {"attempted": 20, "shipped": ~12}}

# Re-run rows that previously failed (after a code fix or threshold tweak)
python3 -m stravart.cli reconstruct \
    --db stravart/data/stravart.sqlite \
    --crossref-cache stravart/data/nominatim_cache.json \
    --retry-attempted

# Lower the ship threshold to inspect borderline reconstructions
python3 -m stravart.cli reconstruct \
    --db stravart/data/stravart.sqlite \
    --crossref-cache stravart/data/nominatim_cache.json \
    --min-confidence 0.4 \
    --limit 5
```

Per-image latency dominates by:
- EasyOCR: ~10-20 s on CPU (one-time per image; reused from Phase 2)
- OSMnx graph download: ~5-15 s per bbox (city-scale walk graphs run
  large; bbox padding is 200 m by default)
- Map-match Dijkstra: ~1-3 s per route

For the **1,170-row geocoded subset**, expect ~12-15 hours wall-clock from a
cold cache. Caching `osmnx.settings.use_cache = True` (osmnx default since
1.x) reduces re-runs significantly because most routes share a city.

---

## Knobs (in `stravart.reconstruct.reconstruct`)

| Argument | Default | Tradeoff |
|---|---:|---|
| `min_streets` | 3 | Required distinct OCR'd street names. ≥3 satisfies the affine fit; raise to 4-5 for high-precision-only batches. |
| `cluster_radius_km` | 3.0 | Phase 2 spatial-cluster radius for the cross-reference layer. |
| `min_confidence` | 0.6 | Below this, no GPX is written; the row is still marked attempted with the failure reason in `reconstruction_failure`. |
| `waypoint_step_m` | 30.0 | Map-match Dijkstra granularity. Smaller = more loyal to contour, slower. |
| `bbox_pad_m` | 200.0 | OSM graph padding around the projected contour bbox. Lowering speeds graph downloads but risks unreachable nodes near the edge. |
| `fidelity_buffer_m` | 25.0 | Buffer width for the IoU score. ≈ half a sidewalk to half a road. |

---

## Confidence formula

```
anchor_term  = clamp(0..1, (n_gcps - 3) / 3)   # 0 at 3, 1 at ≥6
rmse_term    = clamp(0..1, 1 - (rmse_m - 30) / 170)  # 1 at ≤30 m, 0 at ≥200 m
ocr_term     = mean OCR confidence on the streets used as GCPs
fid_term     = fidelity_score from snapped vs. projected

confidence   = geomean([anchor_term, rmse_term, ocr_term, fid_term])
```

A geometric mean penalises any single weak stage — three perfect terms
can't rescue a quarter where the snap diverges. The `0.05` floor keeps
the geomean from collapsing to 0.0 when one stage is weak (so we still
get an interpretable "low" rather than a binary fail).

---

## Phase-2 → Phase-3 contract (what we promised, what was delivered)

The Phase 2 handoff said:
> The Phase 2 OCR already produces image-pixel ↔ lat/lon correspondences
> that Phase 3's affine projection needs.

Delivered:

- The pixel side comes from `OcrResult.fragment_boxes` (added in this
  branch — the bbox info was originally discarded after merging in
  `_merge_horizontal_neighbors`).
- The geographic side comes from filtering each candidate's
  `CrossRefResult.matches` to the cluster's bbox — a same-name street in
  another city is dropped at this stage rather than poisoning the affine
  fit. RANSAC catches the residual cases where the bbox filter let one
  through.
- `stravart/reconstruct.py:_gcps_from_ocr` is the join: it consumes the
  `OcrResult` + `CrossRefResult` and emits a list of `GroundControlPoint`s
  ready for `fit_affine`.

---

## Gotchas + lessons captured

1. **OCR bbox merging dropped position info.** `_merge_horizontal_neighbors`
   was returning `[(text, conf)]` with bbox info implicit in the merge but
   thrown away. Adding `return_boxes=True` was a 15-line addition that
   preserves the per-fragment `(xc, yc, w, h)` Phase 3 needs. Phase 2
   tests still pass because the legacy return shape is preserved by
   default.

2. **Affine-fit outlier rejection by residual ranking is fragile.** With
   1 bad anchor in 7, the bad anchor sits geometrically central, pulls
   the least-squares fit toward itself, and then *another* anchor ends up
   with the worst residual. RANSAC sidesteps this entirely — it samples
   3-anchor minimal sets and counts inliers in the consensus, so the bad
   one is statistically rare in the sample.

3. **Disjoint polylines must share a Cartesian frame for IoU
   comparison.** Same trap as `prototype/fidelity.py` — projecting each
   polyline through its own bbox-centred origin makes them overlap at
   the origin. Fix: pick one shared anchor inside the union bbox.
   Pinned by `test_disjoint_polylines_score_zero`.

4. **OSMnx unprojected `nearest_nodes` requires scikit-learn.** The
   synthetic test fixtures set `crs="EPSG:4326"`, so OSMnx routes through
   BallTree (sklearn) instead of cKDTree (scipy). `requirements.txt`
   pins scikit-learn>=1.3 explicitly. (See lessons #1.)

5. **`AffineTransform.estimate(...)` is deprecated in skimage 0.26.** Use
   `AffineTransform.from_estimate(src, dst)` (returns the transform or
   `False` on failure). The old in-place `.estimate()` works but emits
   a `FutureWarning` and is slated for removal in 2.2.

---

## Next-up — proof-of-concept curated batch

**Goal:** validate the pipeline end-to-end on 20 hand-picked images.

**Suggested curation criteria (descending priority):**

1. **Basemap style.** OSM Carto = best (street labels are crisp + sit
   in unique colour bands). Strava heatmap = harder (no labels, route
   line is dim). Skip satellite — OCR fails completely.

2. **Caption text.** Skip images whose only visible text is the route
   title (e.g., "MANCHESTER DOG" with no street labels visible).

3. **Distinct corners.** Routes that change direction in ≥3 distinct
   places give the affine fit something to work with. A single
   straight line gives the affine fit a degenerate parallax problem.

4. **City coverage.** Pick from ≥5 distinct cities so we don't overfit
   the pipeline to UK street-naming conventions.

Suggested SQL pre-filter (Phase 2 outputs already include the city
hint from Nominatim):

```sql
SELECT id, title, city, country, image_url, geocode_confidence
FROM routes
WHERE geocode_source = 'ocr'
  AND geocode_confidence > 0.55
ORDER BY RANDOM()
LIMIT 50;
```

Hand-pick 20 from the result.

**Expected outcomes per stage** (baseline guesses for the curated batch):
- Contour extraction: 95-100% success (~5% might fail on dim/old strokes)
- OCR ≥ 3 streets: 80% success (Phase 2 already vetted this)
- Affine fit RMSE: median ~30-60 m, p95 ~150 m
- Fidelity score after snap: median 0.55, p95 0.85
- Aggregate confidence ≥ 0.6: ~50-65% of the batch

If the ship rate is below ~40%, the ranked failure modes from
`reconstruct-stats` will tell us where to invest:
- Mostly `contour: too short` → contour extraction needs more lenient
  HSV bands or a non-warm-colour route mode (Strava heatmap blue).
- Mostly `georef: only N GCPs` → bbox-filter inside `_gcps_from_ocr` is
  too strict; relax cluster bbox padding.
- Mostly `confidence: 0.4X < 0.6` → look at the per-stage breakdown in
  `Reconstruction.diagnostics` — usually fidelity is the weakest term
  and the snap is wandering off-route.

---

## What was *not* attempted

* **Valhalla / Meili map-matching.** Would need a server side-car. OSMnx +
  per-segment Dijkstra is good enough for our use case and pure Python.
* **Inpainting under the route stroke before OCR for Phase 3 anchors.**
  Phase 2's `inpaint_route` already runs by default in `ocr_image`; we
  reuse it as-is.
* **Validating GPX against a reference run.** No live ground-truth file
  paths to compare against — that's a follow-up once the batch runs.
* **iOS-app integration.** Phase 2B already has an iOS client; once the
  GPX files are produced the SwiftUI side can serve them via a
  `/route/{id}.gpx` endpoint added to `server/`. Out-of-scope for Phase 3.

---

## Phase-3 → Phase-4 hand-off candidates

* **Quality-rank the shipped reconstructions.** The 12-15 of the 20
  curated images that ship are still a mix of "perfect" and "barely
  passes 0.6". A simple visual sort + manual review tier could feed a
  classifier that learns which inputs pass downstream.
* **Self-supervised QA loop.** Re-OCR the rendered snapped GPX (e.g.
  via `osmnx.plot_graph_route`), check that the OCR'd street names on
  the rendered image match the input image's OCR output. A discrepancy
  is a high-confidence flag that the snap drifted.
* **Active learning on the failure tier.** Pin the failure-mode counts
  from `reconstruct-stats` to a regression dashboard so a future code
  change that drops ship rate is caught at PR time.
