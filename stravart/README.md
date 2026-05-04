# stravart finder — Phase 1

Offline pipeline + search index for [strav.art](https://www.strav.art) gallery routes. Phase 1 of the multi-phase "find existing GPS art near me" feature.

## What this is

DoodleRun's primary feature is *generating* GPS art from shape templates. The complement is *discovering* GPS art that already exists in your area: someone has already plotted out a perfect dog route through your neighbourhood, and we'd rather show you that than reinvent it.

`strav.art` is the largest curated gallery of Strava-art routes online, but it's a Squarespace site with no API and no GPX downloads — just images. This package builds a searchable local catalog from those images:

```
strav.art galleries
  ├── Playwright scraper          (scrape.py)
  ├── Title parser + gazetteer    (parse_title.py)
  ├── Nominatim geocoder + cache  (geocode.py)
  ├── SQLite + R-tree index       (db.py)
  └── Haversine search API        (search.py)
```

The output is a single ~800 KB SQLite file (`stravart/data/stravart.sqlite`) bundleable into the iOS app. Phase 2 will wire this DB to the existing route generator as a fallback path; Phase 3+ will reconstruct GPX traces from the gallery images.

## Quick start

```bash
pip install -r stravart/requirements.txt
python -m playwright install chromium

# Scrape + index everything
python -m stravart.cli scrape --out stravart/data/raw.jsonl
python -m stravart.cli index --jsonl stravart/data/raw.jsonl --db stravart/data/stravart.sqlite

# Local search
python -m stravart.cli stats --db stravart/data/stravart.sqlite
python -m stravart.cli search --db stravart/data/stravart.sqlite \
    --lat 51.7521 --lon -0.336 --radius 60 --query dog
```

A pre-built DB is checked in at `stravart/data/stravart.sqlite` (1654 rows, 41 geocoded — re-run with the gazetteer expanded if you want more hits).

## DB schema

```sql
routes(id, title, category, subcategory, city, country,
       lat, lon, geocode_confidence,
       image_url, stravart_url, distance_estimate_km, scraped_at)

routes_rtree                 -- R*Tree virtual table on (lat, lon)
category_synonyms(term, slug)
meta(key, value)
```

`UNIQUE(image_url)` makes re-runs idempotent. `geocode_confidence` is `1.0` for gazetteer-resolved cities, `0.5` for em-dash-split fallback hits, `0.0` for items with no location signal.

## Known limitations (Phase 1)

- **~3 % geocode coverage.** Most strav.art titles don't include a city. A bigger gazetteer or OCR-from-image (Phase 3) would lift this dramatically.
- **No GPX, no exact route polyline.** The image URL is the only artefact. Phase 3 will try to vectorise the route from the image.
- **Stale tolerance only.** No incremental scraping yet — `scrape` rewrites the JSONL each time.
- **Em-dash fallback can mis-flag.** Titles like "BE STRONG, BUT GENTLE 🐘" produce a low-confidence "But Gentle" "city" that Nominatim may resolve to a real place. The DB stores `geocode_confidence` so the search layer can demote these.

## Tests

```bash
pytest stravart/tests/
```

Unit tests cover the title parser, synonym table, DB schema, and search algorithm. No network or browser required.
