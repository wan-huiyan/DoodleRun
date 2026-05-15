# Phase 4a → Phase 4b verdict comparison

**Method.** Paper-trace using each route's persisted Phase 4a numbers
(`per_image/route_NNNNN/reconstruction.json`) re-graded by the new
gate in `stravart/reconstruct.py`. No live re-run; no API budget burned.
The pipeline OUTPUTS (contour, OCR, georef, snap) are byte-identical to
run #2 — only the VERDICT changes.

For each row: applied (1) ``min_gcps≥5`` (post-dedup), (2) ``min_rmse≥0.5m``
when ``n_anchors_post≥4``, (3) recomputed confidence with the same formula,
(4) classified as ``shipped/review/fail`` against the new 0.4 / 0.6 thresholds,
(5) routed OCR0 cases with title-lat/lon into the centroid_project fallback.

| ID | title | Phase 4a verdict | Phase 4b verdict | what changed |
|---:|---|---|---|---|
| 910 | London Marathon | SHIP (0.60) | SHIP-strict | unchanged ✓ |
| 921 | Hackney Horse | SHIP (0.62) | SHIP-strict | unchanged ✓ |
| 53 | Regent's Park | FAIL-CONF (0.58) | REVIEW (0.58) | was silently dropped — now in review queue |
| 584 | Travelling Elephant | FAIL-CONF (0.50) | REVIEW (0.50) | same — was silently dropped, now reviewable |
| 60 | Hampstead Heath | FAIL-CONF (0.28) | FAIL-conf (0.28<0.4) | conf now matches the explicit gate |
| 942 | London Bear | FAIL-CONF (0.31) | FAIL-conf (0.31<0.4) | same |
| 577 | Dumbo Cambridge | FAIL-CONF (0.37) | FAIL-min_gcps(3<5) | failure reason corrected (only 3 GCPs) |
| 1272 | St Albans Shark | FAIL-CONF (0.29) | FAIL-min_gcps(4<5) | failure reason corrected (only 4 GCPs) |
| 1294 | Whale in Wales | FAIL-CONF (0.24) | FAIL-min_gcps(3<5) | failure reason corrected (only 3 GCPs) |
| 5 | Manchester Dog | FAIL-EARLY (OCR0) | CITY-SCALE (0.50) | NEW: decorative card via centroid fallback |
| 30 | Vienna Doggo | FAIL-EARLY (OCR0) | CITY-SCALE | NEW |
| 208 | Berlin Mutt | FAIL-EARLY (OCR0) | CITY-SCALE | NEW |
| 248 | 1st Berlin Drawing | FAIL-EARLY (OCR0) | CITY-SCALE | NEW |
| 799 | Bullfight in Munich | FAIL-EARLY (OCR0) | CITY-SCALE | NEW |
| 800 | Munich Lion | FAIL-EARLY (OCR0) | CITY-SCALE | NEW |
| 1135 | Rotterdam Turtles | FAIL-EARLY (OCR0) | CITY-SCALE | NEW |
| 1359 | Amsterdam Ajax | FAIL-EARLY (OCR0) | CITY-SCALE | NEW |
| 1565 | Hamburg Strava | FAIL-EARLY (OCR0) | CITY-SCALE | NEW |
| 36 | West Devon | FAIL-EARLY (OCR0) | FAIL-OCR0-NoLatLon | unrecoverable — no title-latlon |
| 1333 | Paris GPS Drawing | FAIL-EARLY (XREF) | FAIL-XREF | unrecoverable — crossref fails |

## Tallies

| | Phase 4a | Phase 4b |
|---|---:|---:|
| Strict ship (runnable) | 2/20 | 2/20 |
| Review tier (runnable, manual approval) | 0 (silent fail) | 2/20 |
| City-scale (decorative card) | 0 (no fallback) | 9/20 |
| Honestly rejected | 18/20 (mostly wrong reason) | 7/20 |

## What the diagnostic PNGs show

* **`city_scale_NNNNN.png` (new)** — 3-panel: original / extracted contour /
  contour placed at the city centroid. Confirms the shape is preserved and the
  geographic placement is at city-scale (~4 km wide, anchored on the title
  centroid). These are decorative cards, never navigable routes.

* **`phase4a_poc/diagnostics/route_NNNNN_summary.png` (Phase 4a, unchanged)** —
  4-panel: original / contour / OCR anchors / projected-vs-snapped overlay.
  Phase 4b doesn't change these — same image goes through the same pipeline
  up to the gate. What's new is the verdict line at the top.

## Options 1+2 — implemented, evaluated, parked

Options 1 (denser waypoints) and 2 (k-shortest-paths + Fréchet shape
rerank) are merged but the empirical result is a **negative finding**:
they don't improve fidelity on the elephant route, the route the user
remembered as the canonical "wrong-turn snap distortion" case.

`sweep_options.py` ran 5 parameter combinations on #584 with the RANSAC
seed pinned to remove run-to-run noise:

```
label                                  step  k   wp  reranked  fréchet  fidelity  iou
baseline (Phase 4a defaults)            30   1  170      0       685    0.190    0.316
Option 1 only (denser waypoints)        15   1  329      0       685    0.191    0.318
Option 2 only (k=3 shape rerank)        30   3  170      0       685    0.190    0.316
Options 1+2 (15m + k=3 + shape rerank)  15   3  329      0       685    0.191    0.318
sparser + larger K                      50   5  104      0       685    0.189    0.314
```

All five cells produce a Fréchet distance of 685 m and fidelity ~0.19.
`reranked_segments=0` everywhere. Why options 1+2 don't help on this
route:

* At waypoint spacings of 15–50 m on a dense city street graph, the
  `shortest_simple_paths` generator returns only one path between most
  consecutive snapped node pairs. There's nothing to rerank.
* The shape divergence (685 m Fréchet) isn't "Dijkstra picked the wrong
  of equally-good alternatives" — it's "the projected cartoon polyline
  goes diagonally between streets, and any path that follows real streets
  has to make detours that the cartoon doesn't have."
* Local re-ranking can't fix that mismatch. A GLOBAL path optimisation
  (HMM-based map matcher, Valhalla Meili, `fmm`) that scores the entire
  route's likelihood against the observed shape — not segment by segment
  — is the right tool.

The infrastructure (k-paths generator + Fréchet rerank in `mapmatch.py`)
is left in place behind opt-in knobs (`--mapmatch-k-paths` > 1) so we
can experiment further without removing it. Defaults are reverted to
the Phase 3 values (30 m, k=1) — no functional change to the catalog
batch.

The previous "negative result" sweep without RANSAC seeding looked
encouraging (fidelity 0.19 → 0.45) but that was entirely RANSAC affine-
fit randomness. Pinning the seed exposed the real outcome.

## What now

To actually fix the wrong-turn problem the user remembers, **option 3
(proper HMM / probabilistic map matcher)** is needed. Candidates:

* **`fmm`** (Fast Map Matching, github.com/cyang-kth/fmm) — Python +
  C++; an installable Python package. Likely the cheapest integration.
* **Valhalla Meili** — production-grade but needs a Valhalla server
  side-car. More setup.
* **In-house HMM** over OSM edges — meaningful build, but no external
  dependency. Conceptually: emission = distance of observation from
  edge centerline; transition = path-length / unreachable penalty
  between consecutive states. Viterbi over edge states yields the
  globally most-likely route.

The Phase 4b PR ships honestly: the gate works, the city-scale
fallback works, the wrong-turn problem on review-tier routes is a
known limitation that the next phase (4c) should address.
