"""End-to-end indexer: parse scraped JSONL -> geocode -> SQLite.

Idempotent: re-running over the same JSONL is safe (UPSERT on image_url) and
will only re-geocode rows the cache hasn't already seen.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .db import Route, connect, count_geocoded, count_routes, seed_synonyms, set_meta, transaction, upsert_route
from .geocode import Geocoder
from .parse_title import parse_title
from .scrape import iter_jsonl
from .synonyms import SYNONYMS


log = logging.getLogger("stravart.pipeline")


def index_jsonl(
    jsonl_path: Path,
    db_path: Path,
    geocode_cache_path: Path | None = None,
    skip_geocoding: bool = False,
) -> tuple[int, int]:
    """Read scraped items, parse titles, geocode, write to SQLite.

    Returns (rows_indexed, rows_geocoded).
    """
    geocode_cache_path = geocode_cache_path or db_path.with_name("geocode_cache.json")
    geo = None if skip_geocoding else Geocoder(geocode_cache_path)

    conn = connect(db_path)
    try:
        with transaction(conn):
            seed_synonyms(conn, SYNONYMS)

        total = 0
        geocoded = 0
        with transaction(conn):
            for item in iter_jsonl(jsonl_path):
                total += 1
                parsed = parse_title(item["title"])

                lat = lon = None
                conf = parsed.confidence
                country = parsed.country
                city = parsed.city

                if geo and parsed.city:
                    res = geo.geocode(parsed.city, country=parsed.country)
                    if res is not None:
                        lat, lon = res.lat, res.lon
                        country = country or res.country
                        geocoded += 1
                    else:
                        # geocode miss demotes confidence so the search layer can
                        # show "approximate" markers if it wants
                        conf = min(conf, 0.25)

                upsert_route(conn, Route(
                    title=item["title"],
                    category=item["category"],
                    subcategory=parsed.shape or None,
                    city=city,
                    country=country,
                    lat=lat,
                    lon=lon,
                    geocode_confidence=conf,
                    image_url=item["image_url"],
                    stravart_url=item["stravart_url"],
                    scraped_at=item["scraped_at"],
                ))
            set_meta(conn, "indexed_at", datetime.now(timezone.utc).isoformat())
            set_meta(conn, "schema_version", "1")

        log.info(
            "indexed %d rows (%d geocoded) -> %s",
            total, geocoded, db_path,
        )
        return total, geocoded
    finally:
        conn.close()


def index_items(
    items: Iterable[dict],
    db_path: Path,
    skip_geocoding: bool = True,
) -> tuple[int, int]:
    """Test-friendly variant: index pre-formed items dict-by-dict."""
    conn = connect(db_path)
    try:
        with transaction(conn):
            seed_synonyms(conn, SYNONYMS)
        total = 0
        with transaction(conn):
            for item in items:
                parsed = parse_title(item.get("title", ""))
                upsert_route(conn, Route(
                    title=item["title"],
                    category=item["category"],
                    subcategory=parsed.shape or None,
                    city=item.get("city") or parsed.city,
                    country=item.get("country") or parsed.country,
                    lat=item.get("lat"),
                    lon=item.get("lon"),
                    geocode_confidence=item.get("geocode_confidence", parsed.confidence),
                    image_url=item["image_url"],
                    stravart_url=item.get("stravart_url", ""),
                    scraped_at=item.get("scraped_at", datetime.now(timezone.utc).isoformat()),
                ))
                total += 1
        return total, count_geocoded(conn)
    finally:
        conn.close()


def stats(db_path: Path) -> dict:
    """Quick sanity counts for CLI / smoke tests."""
    conn = connect(db_path)
    try:
        return {
            "total": count_routes(conn),
            "geocoded": count_geocoded(conn),
            "by_category": dict(conn.execute(
                "SELECT category, COUNT(*) c FROM routes GROUP BY category ORDER BY c DESC"
            ).fetchall()),
        }
    finally:
        conn.close()
