"""Search API: given (lat, lon, radius_km, query), return matching strav.art routes.

Two-stage filter:
  1. R-tree bounding-box prefilter on a degree-degree box conservatively sized
     for the requested radius. Cheap.
  2. Haversine distance check to drop the bbox corners. Sort ascending.

Category resolution prefers the DB synonyms table (so the seed is hot-editable
in production); falls back to the in-process map if the DB hasn't been seeded.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import Sequence

from . import synonyms as syn_module
from .db import lookup_synonym


EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class SearchHit:
    id: int
    title: str
    category: str
    subcategory: str | None
    city: str | None
    country: str | None
    lat: float
    lon: float
    image_url: str
    stravart_url: str
    distance_km: float
    geocode_confidence: float


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _bbox(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Conservative lat/lon bounding box for an R-tree prefilter.

    1 degree latitude ≈ 111 km; longitude scales with cos(lat). The box is
    intentionally wider than the great-circle radius because R-tree boxes are
    cheap and we'd rather over-fetch than miss a corner.
    """
    dlat = radius_km / 111.0
    cosphi = max(0.01, math.cos(math.radians(lat)))
    dlon = radius_km / (111.0 * cosphi)
    return (lat - dlat, lat + dlat, lon - dlon, lon + dlon)


def resolve_category(conn: sqlite3.Connection, term: str | None) -> str | None:
    """Resolve a free-text query to a category slug, DB first then in-process map."""
    if not term:
        return None
    db_hit = lookup_synonym(conn, term)
    if db_hit:
        return db_hit
    return syn_module.resolve_category(term)


def search(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    radius_km: float,
    query: str | None = None,
    limit: int = 50,
) -> list[SearchHit]:
    """Return up to `limit` strav.art routes near (lat, lon), ordered by distance."""
    if radius_km <= 0:
        return []
    min_lat, max_lat, min_lon, max_lon = _bbox(lat, lon, radius_km)
    category = resolve_category(conn, query) if query else None

    sql = (
        "SELECT r.* FROM routes r JOIN routes_rtree rt ON rt.id = r.id "
        "WHERE rt.min_lat >= ? AND rt.max_lat <= ? "
        "  AND rt.min_lon >= ? AND rt.max_lon <= ?"
    )
    params: list[object] = [min_lat, max_lat, min_lon, max_lon]
    if category:
        sql += " AND r.category = ?"
        params.append(category)

    rows = conn.execute(sql, params).fetchall()
    hits: list[SearchHit] = []
    for r in rows:
        d = haversine_km(lat, lon, r["lat"], r["lon"])
        if d > radius_km:
            continue
        hits.append(SearchHit(
            id=r["id"],
            title=r["title"],
            category=r["category"],
            subcategory=r["subcategory"],
            city=r["city"],
            country=r["country"],
            lat=r["lat"],
            lon=r["lon"],
            image_url=r["image_url"],
            stravart_url=r["stravart_url"],
            distance_km=d,
            geocode_confidence=r["geocode_confidence"],
        ))
    hits.sort(key=lambda h: h.distance_km)
    return hits[:limit]


def search_as_dicts(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    radius_km: float,
    query: str | None = None,
    limit: int = 50,
) -> list[dict]:
    return [h.__dict__ for h in search(conn, lat, lon, radius_km, query, limit)]
