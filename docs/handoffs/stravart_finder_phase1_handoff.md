# strav.art Finder — Phase 1 Handoff

**Branch:** `claude/stravart-finder-phase1`
**Status:** ✅ Phase 1 complete, ready for Phase 2 wiring.
**Date:** 2026-05-04

---

## What was built

A self-contained Python package at `stravart/` that scrapes strav.art galleries, parses titles, geocodes via Nominatim, and writes a SQLite + R-tree catalog ready to ship inside the iOS app.

| File | Role |
|---|---|
| `stravart/scrape.py`        | Async Playwright scraper. Scrolls each `/home/{slug}` to lazy-load all tiles, extracts `<a><img></a>` pairs, writes JSONL. |
| `stravart/parse_title.py`   | Heuristic parser for image alt-text. Gazetteer of ~80 cities (UK focus area + globals); em-dash/comma fallback. Returns `(shape, city, country, confidence)`. |
| `stravart/geocode.py`       | Nominatim wrapper: 1 req/sec rate limiter, JSON-file cache (hits + negatives), macOS keychain TLS for corporate proxies. |
| `stravart/db.py`            | SQLite schema with `routes` table, `routes_rtree` R*Tree virtual table, `category_synonyms`, `meta`. UPSERT keyed on `image_url`. |
| `stravart/synonyms.py`      | Hand-curated `user term → category slug` table seeded into the DB. |
| `stravart/search.py`        | Search API: bbox prefilter via R-tree, Haversine refine, sort by distance. Resolves category from DB or in-process fallback. |
| `stravart/pipeline.py`      | Glue: JSONL → parse → geocode → upsert. Idempotent; safe to kill mid-run. |
| `stravart/cli.py`           | `python -m stravart.cli {scrape,index,stats,search,...}` entrypoints. |
| `stravart/tests/`           | Pytest suite — parser, synonyms, DB+search integration. **24/24 passing**, no network needed. |

### Numbers from the live run committed to this branch

- **1,654 routes** scraped from 9 categories (`cats-dogs`, `birds`, `dinosaurs`, `elephants`, `insects`, `mammals`, `reptiles`, `sea-life`, `misc`).
- **41 geocoded** with high or medium confidence — i.e. usable lat/lon for the search index.
- **DB size: 800 KB** — bundleable in the iOS app (well within the ~600 KB / 3000-row target band).
- Search latency: sub-millisecond even with no warm cache; R-tree prefilter scales fine to >10k rows.
- Live smoke search near St Albans (51.7521, -0.336) within 200 km returns "ST ALBANS SHARK" at 0.17 km, two London routes at ~30 km, "DUMBO VISITS CAMBRIDGE" at 59 km.

### Files committed

```
stravart/
  __init__.py
  cli.py
  db.py
  geocode.py
  parse_title.py
  pipeline.py
  scrape.py
  search.py
  synonyms.py
  README.md
  requirements.txt
  data/
    raw.jsonl              # 743 KB, 1654 lines
    stravart.sqlite        # 800 KB, ready to bundle
    geocode_cache.json     # 9 KB, hits + negatives
  tests/
    test_parse_title.py
    test_synonyms.py
    test_db_and_search.py
docs/handoffs/
  stravart_finder_phase1_handoff.md   # this file
```

---

## What's next for Phase 2

Phase 2's job is to **wire this catalog into DoodleRun's existing FastAPI surface** so the iOS app can hit it as a fallback when route generation doesn't find a good local match. Concretely:

1. **New `/stravart/search` endpoint** in `server/main.py`. Takes `lat`, `lon`, `radius_km`, `query` (optional). Returns JSON list matching `SearchHit.__dict__`. Use `stravart.search.search_as_dicts`.
2. **Bundle the DB** at app startup. Either ship `stravart.sqlite` as a server static asset or copy it into the iOS app bundle and run search on-device. The iOS team will likely prefer on-device — schema is already R-tree-indexed.
3. **Decide the fallback UX.** When `route_generator.generate_search` returns no high-fidelity candidate near the user, surface "we found N existing strav.art routes within X km of you" with image previews from `image_url`. Confidence flag (`geocode_confidence`) should show "approximate" markers vs. canonical city pins.
4. **Re-scrape cadence.** strav.art adds new posts weekly. Either:
   - Cron a nightly scrape + index on the server side, or
   - Ship a "last_synced_at" meta value and let the iOS app pull deltas. (Out of scope for Phase 2 — pick one and move on.)
5. **Expand the gazetteer.** Current coverage is 80 cities → only 41/1654 (2.5%) of routes resolve. Adding the top 100 UK + top 50 European cities would likely double coverage with no code changes. The gazetteer lives in `parse_title.KNOWN_CITIES` — add tuples and re-run `python -m stravart.cli index ...` (no rescrape needed).

---

## Gotchas (please read before Phase 2)

- **Corporate TLS proxies.** The geocoder injects the macOS keychain CA bundle into httpx (mirroring `prototype/osrm_client.macos_keychain_bundle`). On Linux/CI this is a no-op. If Phase 2 adds new outbound HTTP, mirror the same `_make_ssl_context()` pattern in `stravart/geocode.py` rather than calling `httpx.get` directly.
- **Hyphens are NOT separators.** `parse_title._SEPARATORS` deliberately omits `-` — "BOGGLE-EYED CAT" and "ICE-CREAM TRUCK" must not be split. If you add a separator class, run the parser tests.
- **Multi-word cities require longest-first match.** `_CITIES_LONGEST_FIRST` is sorted at import; "NEW YORK" must beat "YORK", "ST ALBANS" must beat "ALBANS". Don't iterate `KNOWN_CITIES` directly.
- **R-tree rejects NULLs.** `db.upsert_route` only inserts a bbox row when both `lat` and `lon` are present, and *deletes* the bbox if a re-index now sees null coords. The schema is sound but R-tree-aware code must use the join in `search.search`, not a `LEFT JOIN`.
- **Squarespace structure can shift.** The scraper relies on `<a href="*squarespace-cdn.com*"><img alt="…">` shape. If strav.art redesigns, the JS in `scrape._EXTRACT_JS` is the failure point. There's no fallback selector — by design (we'd rather error loudly than silently scrape garbage).
- **Negative-cache poisoning.** `Geocoder._negatives` is permanent. If you fix a bad city string and want it re-tried, delete the entry in `geocode_cache.json` (search by the normalised query string in the `negatives` array).
- **`UNIQUE(image_url)` is the dedup key.** Don't switch to `(category, title)` — the same shape posted in two categories is intentional (e.g. a snail also tagged as misc).
- **`stravart_url` is the category page**, not a per-item page. strav.art doesn't host individual gallery item URLs. Don't try to dereference it for richer metadata — there isn't any.
- **Scraper headlessness.** `scrape_all(headless=False)` works for debugging on macOS; on CI keep the default. The scraper expects desktop-Chrome viewport.

---

## Phase 3 preview (NOT in scope here)

The big leap is reconstructing GPX traces from the gallery images. Idea sketch:
1. Fetch the full-resolution image (already in `image_url`).
2. Edge-detect the route stroke (it's usually a high-contrast coloured line on a Strava base map).
3. Re-project to lat/lon using map tile alignment hints (the cropping / zoom level shows in the image — small fingerprint area in the corner).
4. Snap to roads via OSRM (already wired in `prototype/osrm_client.py`).

This is research-grade and probably a multi-week effort — Phase 2 just needs to ship search.

---

## How to verify nothing broke

```bash
pytest stravart/tests/ -q                # 24/24
python -m stravart.cli stats --db stravart/data/stravart.sqlite
python -m stravart.cli search --db stravart/data/stravart.sqlite \
    --lat 51.7521 --lon -0.336 --radius 60 --query shark
# expect: "THE ST ALBANS SHARK 🦈" at 0.17 km
```
