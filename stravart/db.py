"""SQLite schema + R-tree spatial index for the strav.art catalog.

The DB is intended to be bundled with the iOS app, so we keep it small: text
columns hold parsed metadata, and a parallel `routes_rtree` virtual table
provides O(log n) bounding-box prefilter. Search code computes Haversine
distance only on the small set returned by the R-tree.

Table layout:

    routes(id PK, title, category, subcategory, city, country, lat, lon,
           geocode_confidence, image_url, stravart_url, distance_estimate_km,
           scraped_at)
    routes_rtree(id, min_lat, max_lat, min_lon, max_lon)   -- VIRTUAL R*Tree
    category_synonyms(term PK, slug)
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS routes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    title                TEXT    NOT NULL,
    category             TEXT    NOT NULL,
    subcategory          TEXT,
    city                 TEXT,
    country              TEXT,
    lat                  REAL,
    lon                  REAL,
    geocode_confidence   REAL    NOT NULL DEFAULT 0.0,
    image_url            TEXT    NOT NULL,
    stravart_url         TEXT    NOT NULL,
    distance_estimate_km REAL,
    scraped_at           TEXT    NOT NULL,
    UNIQUE(image_url)
);

CREATE INDEX IF NOT EXISTS idx_routes_category ON routes(category);
CREATE INDEX IF NOT EXISTS idx_routes_city     ON routes(city);

CREATE VIRTUAL TABLE IF NOT EXISTS routes_rtree USING rtree(
    id,
    min_lat, max_lat,
    min_lon, max_lon
);

CREATE TABLE IF NOT EXISTS category_synonyms (
    term TEXT PRIMARY KEY,
    slug TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class Route:
    title: str
    category: str
    image_url: str
    stravart_url: str
    scraped_at: str
    subcategory: str | None = None
    city: str | None = None
    country: str | None = None
    lat: float | None = None
    lon: float | None = None
    geocode_confidence: float = 0.0
    distance_estimate_km: float | None = None
    id: int | None = None


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the catalog DB, creating the schema if missing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Convenience: BEGIN/COMMIT, rollback on exception."""
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def upsert_route(conn: sqlite3.Connection, r: Route) -> int:
    """Insert or update a route by its unique image_url. Returns row id.

    Keeps `routes_rtree` in sync — only inserts the bbox row when lat/lon are
    present (R*Tree rejects NULL coords).
    """
    cur = conn.execute(
        """
        INSERT INTO routes
            (title, category, subcategory, city, country,
             lat, lon, geocode_confidence,
             image_url, stravart_url, distance_estimate_km, scraped_at)
        VALUES (?,?,?,?,?, ?,?,?, ?,?,?,?)
        ON CONFLICT(image_url) DO UPDATE SET
            title=excluded.title,
            category=excluded.category,
            subcategory=excluded.subcategory,
            city=excluded.city,
            country=excluded.country,
            lat=excluded.lat,
            lon=excluded.lon,
            geocode_confidence=excluded.geocode_confidence,
            stravart_url=excluded.stravart_url,
            distance_estimate_km=excluded.distance_estimate_km,
            scraped_at=excluded.scraped_at
        """,
        (
            r.title, r.category, r.subcategory, r.city, r.country,
            r.lat, r.lon, r.geocode_confidence,
            r.image_url, r.stravart_url, r.distance_estimate_km, r.scraped_at,
        ),
    )
    rowid = cur.lastrowid
    if rowid == 0:
        # ON CONFLICT update path doesn't bump lastrowid — look it up.
        rowid = conn.execute(
            "SELECT id FROM routes WHERE image_url = ?", (r.image_url,)
        ).fetchone()["id"]

    if r.lat is not None and r.lon is not None:
        # Use a degenerate bbox (point) so range queries still work.
        conn.execute(
            "INSERT OR REPLACE INTO routes_rtree(id, min_lat, max_lat, min_lon, max_lon) "
            "VALUES (?,?,?,?,?)",
            (rowid, r.lat, r.lat, r.lon, r.lon),
        )
    else:
        conn.execute("DELETE FROM routes_rtree WHERE id = ?", (rowid,))
    return rowid


def seed_synonyms(conn: sqlite3.Connection, synonyms: dict[str, str]) -> None:
    """Replace the synonym table contents with the provided mapping."""
    conn.execute("DELETE FROM category_synonyms")
    conn.executemany(
        "INSERT INTO category_synonyms(term, slug) VALUES (?, ?)",
        list(synonyms.items()),
    )


def lookup_synonym(conn: sqlite3.Connection, term: str) -> str | None:
    row = conn.execute(
        "SELECT slug FROM category_synonyms WHERE term = ?", (term.lower(),)
    ).fetchone()
    return row["slug"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def all_routes(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    return conn.execute("SELECT * FROM routes ORDER BY id").fetchall()


def count_routes(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM routes").fetchone()["n"]


def count_geocoded(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM routes WHERE lat IS NOT NULL"
    ).fetchone()["n"]
