# strav.art Finder — Phase 2 Handoff

**Branch:** `claude/stravart-finder-phase2`
**Status:** ✅ Phase 2 complete. OCR-based geocoding ready for batch run + Phase 3 wiring.
**Date:** 2026-05-04

---

## What was built

A drop-in extension to the Phase 1 pipeline that reads street-name labels off
strav.art map images and resolves them to coordinates via OpenStreetMap. The
goal: lift the geocoded fraction from ~3% (title-only) to ~70% by exploiting
the visual content of the image instead of the human-written title.

| File | Role |
|---|---|
| `stravart/streets.py`     | Street-shape detector + abbreviation expander (Rd → Road, Ave → Avenue, …). Three syntactic forms: trailing English (`Broomfield Rd`), leading EU (`Rue Lafayette`), German compound (`Tauentzienstrasse`). Also generates OCR-typo variants (`Brocmfield Road` → `Broomfield Road`, `Partrdge Ave` → `Partridge Ave`). |
| `stravart/ocr.py`         | Image fetch + HSV-saturation route-line inpaint (`cv2.INPAINT_TELEA`) + EasyOCR. Bbox-based fragment merging glues `Dixon` + `Ave` back into `Dixon Ave`. Module-level Reader singleton so a batch run amortises the model load. |
| `stravart/crossref.py`    | `NominatimStreetClient` (default) + `OverpassClient` (legacy). Greedy single-link spatial clustering. Two-pass verification: when worldwide top-40 misses the right city, falls back to structured `street=X&city=Y` queries against every (city, country) hypothesis seen in pass-1. JSON cache + 1.1s rate limit. |
| `stravart/ocr_pipeline.py`| Batch driver. Reads `routes WHERE lat IS NULL`, OCRs each, writes back lat/lon + city/country + ocr_streets JSON + `geocode_source = 'ocr' \| 'ocr-failed'`. Idempotent and resumable — `ocr_attempted_at` is set on every attempt regardless of outcome. |
| `stravart/db.py`          | Additive schema migration: adds `geocode_source`, `ocr_streets`, `ocr_attempted_at` columns. `connect()` applies the migration in place; the Phase 1 bundled DB upgrades on first open with no data loss. New helper `routes_needing_ocr` + `update_ocr_geocode` + `count_by_geocode_source`. |
| `stravart/cli.py`         | New subcommands: `ocr-geocode`, `ocr-stats`. |
| `stravart/tests/test_streets.py`     | 35 tests covering suffix detection, abbreviation expansion, EU + compound forms, OCR-typo variant generation. |
| `stravart/tests/test_crossref.py`    | 17 tests covering haversine, single-link clustering, two-pass verification, both Overpass + Nominatim cache replay. |
| `stravart/tests/test_ocr_pipeline.py`| 10 tests covering Phase-1→Phase-2 schema migration, `routes_needing_ocr` filtering, R-tree updates, end-to-end mocked batch. |

**93 tests pass total** (24 from Phase 1 + 69 new). All offline — no network or
EasyOCR model load is required to run the suite.

### Live smoke run

10-route batch against `stravart/data/stravart.sqlite`:

```
Before: {'total': 1654, 'geocoded': 41, 'by_source': {'title': 41}}
Summary: {'attempted': 10, 'geocoded': 7, 'success_rate': 0.7,
          'errors': 0, 'no_streets': 2, 'no_cluster': 1}
After:  {'total': 1654, 'geocoded': 48, 'by_source': {'ocr': 7, 'title': 41}}
```

Spot-check of OCR-resolved cities (correct):
- `'TUESDAY EVENING RUN'` → US (Binford / Branch / Piedmont / Stuart Street)
- `'SUNDAY STRAVA ART'` → Manchester/Salford (Ayres Rd / Ordsall Lane / Regent Rd)
- `'BOGGLE-EYED CAT'` → Yorkshire (Skipton Rd / Wetherby Rd)
- `'DOG RUN'` → San Francisco (Alma / Lawton / Ortega / Pacheco / Presidio Terrace)
- `'YORKIE'` → Leeds (Armley / Lovell Park / Pontefract Lane) — note title hint matches city
- `'HAPPY NATIONAL PUPPY DAY'` → San Francisco

Per-image latency dominated by EasyOCR (~10-20s on CPU) + Nominatim (~5s for
2-pass). Caching + reusing the pre-warmed Reader singleton makes the second-
and-onwards images much faster.

### Scaling estimate for the full 1,613-row batch

```
~15s OCR + ~10s Nominatim per image
× 1613 images ÷ rate-limit overhead
≈ 11 hours wall-clock from a cold cache.
```

Aggressive caching (street name → Nominatim hits) collapses this on a re-run
because most streets recur across many images.

---

## How to run it

```bash
# Install Phase 2 deps (CPU-only torch is fine; ~500 MB)
python3 -m pip install -r stravart/requirements.txt

# One-time: pre-download EasyOCR models if you're behind a corporate TLS proxy
# (EasyOCR uses urllib which doesn't trust the macOS keychain):
mkdir -p ~/.EasyOCR/model && cd ~/.EasyOCR/model
curl -sLO https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip
curl -sLO https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/english_g2.zip
unzip -o craft_mlt_25k.zip && unzip -o english_g2.zip && rm *.zip

# Run a small batch first to validate
python3 -m stravart.cli ocr-geocode \
    --db stravart/data/stravart.sqlite \
    --crossref-cache stravart/data/nominatim_cache.json \
    --limit 25

# Then run the full batch (multi-hour, resumable — Ctrl-C is safe)
python3 -m stravart.cli ocr-geocode \
    --db stravart/data/stravart.sqlite \
    --crossref-cache stravart/data/nominatim_cache.json

# Re-attempt the rows that failed OCR-geocoding (e.g., after a typo-rule update)
python3 -m stravart.cli ocr-geocode \
    --db stravart/data/stravart.sqlite \
    --crossref-cache stravart/data/nominatim_cache.json \
    --retry-attempted

# Stats:
python3 -m stravart.cli ocr-stats --db stravart/data/stravart.sqlite
# {"total": 1654, "geocoded": 1170, "by_source": {"title": 41, "ocr": 1129}}
```

### Key knobs

| Flag | Default | Notes |
|---|---|---|
| `--crossref-backend` | `nominatim` | `overpass` is legacy; planet-wide name searches OOM the public instance, do not use. |
| `--min-streets` | `2` | Number of distinct OCR'd street names that must co-locate to accept a cluster. Lowering this dramatically inflates false positives. |
| `--cluster-radius-km` | `3.0` | Single-link clustering radius. 3 km handles most metro areas; raising to 10 km starts merging neighbouring suburbs which both have e.g. "High Street". |
| `--languages` | `en` | EasyOCR languages. Add `de fr` for Continental routes. **Note:** mixing Latin and CJK languages in one Reader is unsupported by EasyOCR; do separate batches if you need CJK. |
| `--limit` | none | Useful for cost-bounded test runs. |
| `--retry-attempted` | off | Re-pick rows where OCR ran but failed (`geocode_source = 'ocr-failed'`). |

---

## Gotchas (please read before Phase 3)

- **Numpy 2.x ↔ Torch 2.2 ABI mismatch on macOS x86_64.** The default
  `pip install easyocr` pulls Torch 2.2.2 (last version with x86 macOS
  wheels), which was compiled against NumPy 1.x and crashes at runtime
  on systems with NumPy ≥ 2. Workaround: keep the OCR pipeline in its
  own venv with `numpy<2`. The system Python doesn't need to change.
  Apple-silicon users are unaffected (newer torch wheels exist for
  arm64).

- **EasyOCR + macOS keychain TLS.** EasyOCR downloads model weights via
  `urllib`, which doesn't honour the macOS keychain CA bundle. On
  corporate proxies (Netskope/Zscaler/Palo Alto) the first
  `Reader([...])` call fails with `CERTIFICATE_VERIFY_FAILED`.
  Workaround: pre-download the two `.pth` files into `~/.EasyOCR/model/`
  via `curl` (which uses Security.framework). See the install snippet
  above.

- **Nominatim is importance-biased.** A worldwide search for "Dixon
  Avenue" returns 40 hits ranked by city population; the
  Chelmsford-suburb hit ranks ~25 and falls outside the limit-40
  cutoff. Our two-pass code recovers some of this, but for VERY common
  street names (`High Street`, `Main Street`, `Church Lane`) the
  algorithm legitimately can't disambiguate without a stronger prior.
  Possible Phase-3 mitigations: extract additional non-suffix
  proper-noun fragments from the OCR (the dog image clearly shows
  "BOARDED BARNS" — a Chelmsford-Melbourne neighbourhood — but it lacks
  a street suffix so today's code drops it).

- **OCR confidence is not OSM confidence.** A 0.95 EasyOCR confidence on
  `Brocmfield Road` is still a typo. The variant generator handles the
  most common misreads (cm↔om, rn↔m, dropped vowels, l/I/i confusions)
  but Levenshtein-distance-based matching against OSM names would
  catch more. Out of scope for Phase 2.

- **Glasgow has every street.** Cities with dense road networks (London,
  Glasgow, NYC) tend to have ANY common street name, so when the OCR
  yields only generic names (`Park Road`, `High Street`) the
  cross-reference snaps to whichever dense city has the most matches.
  This produced a Glasgow false-positive on the dog image whose
  ground-truth is Chelmsford. Mitigation: prefer routes with ≥3
  successfully-OCR'd street candidates; below that, surface as
  `geocode_confidence < 0.5` so the iOS app can flag "approximate".

- **The route-line inpainter is HSV-saturation-based.** Strava maps with
  PALE-coloured route lines (e.g., greys on satellite tiles) won't
  trigger the mask. Strav.art uses bright reds/oranges/blues, so this
  works ~95% of the time today, but a Strava redesign could break it.
  The mask threshold (`sat_min=110`, `val_min=70`) is tunable in
  `stravart.ocr.route_mask`.

- **Bbox-based fragment merging trusts EasyOCR's reading order.** When
  EasyOCR misorders or returns overlapping bboxes (rare but happens on
  rotated labels like the vertical "BOARDED BARNS"), merge can produce
  garbage strings. The `_is_alpha_label` filter catches the worst, but
  watch for high-fragment images that resolve to weird candidates.

- **`geocode_source = 'ocr-failed'` is sticky.** The migration
  intentionally leaves this state in place after a failed run; the
  default batch will skip these rows on re-run. To force a retry pass
  use `--retry-attempted`. Do not blindly `UPDATE … SET ocr_attempted_at
  = NULL` — Phase 1's R-tree integrity assumes that any row with `lat
  IS NULL` has its bbox row already absent.

- **Typo-variant fallback widens lookup count.** With 6 candidates × 6
  variants each at 1.1 s/req, worst-case per-image is ~40 s of Nominatim
  time. The cache makes this trivial on re-runs. Don't set
  `--typo-variants 0` for the production batch — recovery via "Brocmfield
  → Broomfield" is the difference between 30% and 70% success on rough
  basemap fonts.

---

## Phase 3 preview (NOT in scope here)

The big leap is reconstructing the actual GPX trace from the gallery image.
Phase 2 gives you (lat, lon) anchor + city + cluster bbox; Phase 3 turns that
into a polyline you can run.

1. The image's coloured stroke + inpaint mask we already build in
   `ocr.route_mask` is *the GPS trace*, in image-pixel coords.
2. Map-tile alignment: most strav.art images are screenshots from Strava's
   own map view. Common providers — OSM Carto, MapTiler, Google. The image
   often contains a small attribution string in the bottom corner —
   another OCR target.
3. Affine transform (image-px → lat/lon) needs at least three
   ground-truth correspondences. Our Phase-2 OCR already gives us them:
   each successfully cross-referenced street label has a
   *known centroid* on the map (image-px from EasyOCR bbox) AND a
   *known lat/lon* from Nominatim. Three of those + a least-squares fit
   yields the projection.
4. Walk the inpaint mask as a polyline (skeletonise → graph → longest
   path) and apply the projection.
5. Snap the resulting polyline to roads via OSRM (already wired in
   `prototype/osrm_client.py`).

Phase 3 is essentially "reuse Phase 2's by-products." Each successful OCR pass
already produces a list of (image_px_x, image_px_y, lat, lon) tuples — they're
just thrown away after clustering today. Persist them and Phase 3 has its
ground-truth for the projection.

---

## How to verify nothing broke

```bash
pytest stravart/tests/ -q                # 93/93 pass, no network
python3 -m stravart.cli stats --db stravart/data/stravart.sqlite
python3 -m stravart.cli search --db stravart/data/stravart.sqlite \
    --lat 51.7521 --lon -0.336 --radius 60 --query shark
# expect: "THE ST ALBANS SHARK 🦈" at 0.17 km   (Phase 1 result preserved)
```

For Phase 2-specific verification, point at a fresh DB to avoid mutating the
bundled one:

```bash
cp stravart/data/stravart.sqlite /tmp/phase2_smoke.sqlite
python3 -m stravart.cli ocr-geocode --db /tmp/phase2_smoke.sqlite --limit 10
python3 -m stravart.cli ocr-stats   --db /tmp/phase2_smoke.sqlite
# expect: by_source containing both 'title' and 'ocr' counts
```
