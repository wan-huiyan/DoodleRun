"""Integration test for db.upsert_route + search.search.

Builds a tiny in-DB catalog of three known points and checks the search results
against hand-computed Haversine distances and category resolution. No Playwright,
no Nominatim — fully offline so this runs in CI and on contributor laptops.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stravart.db import Route, connect, count_geocoded, count_routes, seed_synonyms, upsert_route
from stravart.search import _bbox, haversine_km, resolve_category, search
from stravart.synonyms import SYNONYMS


@pytest.fixture
def db(tmp_path: Path):
    path = tmp_path / "catalog.sqlite"
    conn = connect(path)
    seed_synonyms(conn, SYNONYMS)
    now = datetime.now(timezone.utc).isoformat()
    fixtures = [
        # (title, category, city, country, lat, lon, image_url)
        ("ST ALBANS LION", "mammals", "St Albans", "United Kingdom",
         51.7521, -0.3360, "https://cdn/x/1.jpg"),
        ("MANCHESTER DOG", "cats-dogs", "Manchester", "United Kingdom",
         53.4808, -2.2426, "https://cdn/x/2.jpg"),
        ("LONDON BIRD", "birds", "London", "United Kingdom",
         51.5074, -0.1278, "https://cdn/x/3.jpg"),
        ("UNGEOCODED", "misc", None, None, None, None,
         "https://cdn/x/4.jpg"),
    ]
    for title, cat, city, country, lat, lon, url in fixtures:
        upsert_route(conn, Route(
            title=title, category=cat, city=city, country=country,
            lat=lat, lon=lon, image_url=url, stravart_url="https://www.strav.art/home/x",
            scraped_at=now, geocode_confidence=1.0 if lat is not None else 0.0,
        ))
    yield conn
    conn.close()


def test_haversine_known_distance():
    # London → Manchester ≈ 262 km
    d = haversine_km(51.5074, -0.1278, 53.4808, -2.2426)
    assert 250 < d < 275


def test_bbox_contains_point():
    min_lat, max_lat, min_lon, max_lon = _bbox(51.7521, -0.3360, 30.0)
    assert min_lat < 51.7521 < max_lat
    assert min_lon < -0.3360 < max_lon
    # bbox should be at least ±0.27° lat for a 30 km radius
    assert (max_lat - min_lat) / 2 >= 0.25


def test_counts(db):
    assert count_routes(db) == 4
    assert count_geocoded(db) == 3


def test_resolve_category_via_db(db):
    assert resolve_category(db, "dog") == "cats-dogs"
    assert resolve_category(db, "bird") == "birds"
    assert resolve_category(db, "lion") == "mammals"
    assert resolve_category(db, None) is None


def test_search_near_st_albans_30km(db):
    # St Albans → should hit "ST ALBANS LION" (0 km) and exclude Manchester.
    hits = search(db, lat=51.7521, lon=-0.3360, radius_km=30.0)
    titles = [h.title for h in hits]
    assert "ST ALBANS LION" in titles
    assert "MANCHESTER DOG" not in titles
    # London is ~30 km away — borderline, accept either result but check ordering
    assert hits[0].title == "ST ALBANS LION"
    assert math.isclose(hits[0].distance_km, 0, abs_tol=1.0)


def test_search_with_category_filter(db):
    hits = search(db, lat=51.5074, lon=-0.1278, radius_km=50.0, query="dog")
    # 50 km from London — picks up nothing in cats-dogs (Manchester is 260 km)
    # so we should get 0 hits even though there are routes within 50 km.
    assert hits == []


def test_search_global_radius(db):
    hits = search(db, lat=51.5074, lon=-0.1278, radius_km=10_000.0, query="lion")
    titles = [h.title for h in hits]
    # "lion" maps to mammals, only the St Albans entry matches
    assert titles == ["ST ALBANS LION"]


def test_search_excludes_ungeocoded(db):
    hits = search(db, lat=0, lon=0, radius_km=20_000.0)
    titles = [h.title for h in hits]
    assert "UNGEOCODED" not in titles


def test_upsert_idempotent(db):
    # Inserting the same image_url twice must not duplicate
    now = datetime.now(timezone.utc).isoformat()
    upsert_route(db, Route(
        title="ST ALBANS LION (UPDATED)", category="mammals",
        city="St Albans", country="United Kingdom",
        lat=51.7521, lon=-0.3360,
        image_url="https://cdn/x/1.jpg",
        stravart_url="https://www.strav.art/home/mammals",
        scraped_at=now, geocode_confidence=1.0,
    ))
    assert count_routes(db) == 4
    row = db.execute("SELECT title FROM routes WHERE image_url = ?",
                     ("https://cdn/x/1.jpg",)).fetchone()
    assert row["title"] == "ST ALBANS LION (UPDATED)"
