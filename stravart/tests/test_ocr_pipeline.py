"""Integration tests for the DB schema migration + ocr_pipeline orchestration.

We mock out the heavy bits (image fetch, EasyOCR, Overpass) so this suite
runs offline in <1s.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from stravart import db as dbmod
from stravart import ocr_pipeline
from stravart.crossref import CrossRefResult, GeocodeCluster, OverpassWay
from stravart.db import Route, connect, count_by_geocode_source, routes_needing_ocr, \
    update_ocr_geocode, upsert_route
from stravart.ocr import OcrResult
from stravart.streets import StreetCandidate


# ----------------------------------------------------- DB schema migration

def _make_phase1_db(path: Path) -> None:
    """Create a DB at the *Phase 1* schema (no OCR columns)."""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT,
            city TEXT,
            country TEXT,
            lat REAL,
            lon REAL,
            geocode_confidence REAL NOT NULL DEFAULT 0.0,
            image_url TEXT NOT NULL,
            stravart_url TEXT NOT NULL,
            distance_estimate_km REAL,
            scraped_at TEXT NOT NULL,
            UNIQUE(image_url)
        );
        CREATE VIRTUAL TABLE routes_rtree USING rtree(
            id, min_lat, max_lat, min_lon, max_lon
        );
        CREATE TABLE category_synonyms(term TEXT PRIMARY KEY, slug TEXT NOT NULL);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    conn.execute(
        "INSERT INTO routes(title, category, image_url, stravart_url, scraped_at) "
        "VALUES (?,?,?,?,?)",
        ("OLD ROUTE", "cats-dogs", "u1", "s1", "2026-01-01"),
    )
    conn.commit()
    conn.close()


class TestMigration:
    def test_adds_phase2_columns_in_place(self, tmp_path: Path) -> None:
        db = tmp_path / "old.sqlite"
        _make_phase1_db(db)

        # connect() should add the missing columns without losing the row.
        conn = connect(db)
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(routes)")}
            assert "geocode_source"   in cols
            assert "ocr_streets"      in cols
            assert "ocr_attempted_at" in cols

            row = conn.execute("SELECT * FROM routes WHERE title='OLD ROUTE'").fetchone()
            assert row["geocode_source"] == "title"
            assert row["ocr_streets"] is None
            assert row["ocr_attempted_at"] is None
        finally:
            conn.close()

    def test_migration_is_idempotent(self, tmp_path: Path) -> None:
        db = tmp_path / "x.sqlite"
        connect(db).close()
        connect(db).close()        # second open should not error / duplicate
        conn = connect(db)
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(routes)")}
            # No duplicates implicitly verified by PRAGMA returning unique names.
            assert "ocr_streets" in cols
        finally:
            conn.close()


# ----------------------------------------------------- routes_needing_ocr

class TestRoutesNeedingOcr:
    def test_picks_only_rows_without_lat(self, tmp_path: Path) -> None:
        conn = connect(tmp_path / "db.sqlite")
        upsert_route(conn, Route(title="A", category="cats-dogs",
                                  image_url="u1", stravart_url="s",
                                  scraped_at="t"))
        upsert_route(conn, Route(title="B", category="cats-dogs",
                                  image_url="u2", stravart_url="s",
                                  scraped_at="t", lat=51.0, lon=-0.1))
        rows = routes_needing_ocr(conn)
        assert {r["title"] for r in rows} == {"A"}

    def test_skips_already_attempted_unless_retry(self, tmp_path: Path) -> None:
        conn = connect(tmp_path / "db.sqlite")
        upsert_route(conn, Route(title="A", category="cats-dogs",
                                  image_url="u1", stravart_url="s",
                                  scraped_at="t"))
        update_ocr_geocode(
            conn, route_id=1,
            lat=None, lon=None, confidence=0.0,
            streets_json="[]", attempted_at="2026-05-04T10:00:00Z",
        )
        assert routes_needing_ocr(conn) == []
        again = routes_needing_ocr(conn, retry_attempted=True)
        assert {r["title"] for r in again} == {"A"}

    def test_category_filter(self, tmp_path: Path) -> None:
        conn = connect(tmp_path / "db.sqlite")
        upsert_route(conn, Route(title="A", category="cats-dogs",
                                  image_url="u1", stravart_url="s",
                                  scraped_at="t"))
        upsert_route(conn, Route(title="B", category="birds",
                                  image_url="u2", stravart_url="s",
                                  scraped_at="t"))
        rows = routes_needing_ocr(conn, only_categories=["birds"])
        assert {r["title"] for r in rows} == {"B"}


# ----------------------------------------------------- update_ocr_geocode + R-tree

class TestUpdateOcrGeocode:
    def test_writes_lat_lon_and_rtree_row(self, tmp_path: Path) -> None:
        conn = connect(tmp_path / "db.sqlite")
        upsert_route(conn, Route(title="A", category="cats-dogs",
                                  image_url="u1", stravart_url="s",
                                  scraped_at="t"))
        update_ocr_geocode(
            conn, route_id=1,
            lat=51.75, lon=-0.34, confidence=0.7,
            streets_json='["Broomfield Road","Partridge Avenue"]',
            attempted_at="2026-05-04T10:00:00Z",
        )
        row = conn.execute("SELECT * FROM routes WHERE id=1").fetchone()
        assert row["lat"] == pytest.approx(51.75)
        assert row["geocode_source"] == "ocr"
        assert json.loads(row["ocr_streets"]) == ["Broomfield Road", "Partridge Avenue"]
        rtree = conn.execute("SELECT * FROM routes_rtree WHERE id=1").fetchone()
        assert rtree is not None and rtree["min_lat"] == pytest.approx(51.75)

    def test_failed_run_marks_source_and_skips_rtree(self, tmp_path: Path) -> None:
        conn = connect(tmp_path / "db.sqlite")
        upsert_route(conn, Route(title="A", category="cats-dogs",
                                  image_url="u1", stravart_url="s",
                                  scraped_at="t"))
        update_ocr_geocode(
            conn, route_id=1,
            lat=None, lon=None, confidence=0.0,
            streets_json='[]', attempted_at="2026-05-04T10:00:00Z",
        )
        row = conn.execute("SELECT * FROM routes WHERE id=1").fetchone()
        assert row["lat"] is None
        assert row["geocode_source"] == "ocr-failed"
        assert conn.execute("SELECT COUNT(*) AS n FROM routes_rtree").fetchone()["n"] == 0


# ----------------------------------------------------- run_batch end-to-end (mocked)

class TestRunBatchMocked:
    def test_geocodes_rows_and_writes_back(self, tmp_path: Path) -> None:
        db = tmp_path / "db.sqlite"
        conn = connect(db)
        upsert_route(conn, Route(title="A", category="cats-dogs",
                                  image_url="http://example/a.jpg",
                                  stravart_url="s", scraped_at="t"))
        upsert_route(conn, Route(title="B", category="cats-dogs",
                                  image_url="http://example/b.jpg",
                                  stravart_url="s", scraped_at="t"))
        conn.commit()
        conn.close()

        fake_ocr = OcrResult(
            fragments=[("Broomfield Rd", 0.95), ("Partridge Ave", 0.88)],
            street_candidates=[
                StreetCandidate("Broomfield Rd",  "Broomfield Road",  "road",   0.95),
                StreetCandidate("Partridge Ave",  "Partridge Avenue", "avenue", 0.88),
            ],
        )
        fake_xref = CrossRefResult(
            cluster=GeocodeCluster(
                lat=51.751, lon=-0.34,
                bbox=(51.75, 51.752, -0.341, -0.339),
                streets=["Broomfield Road", "Partridge Avenue"],
                n_ways=2, confidence=0.78,
                city="Chelmsford", country="United Kingdom",
            ),
            matches={
                "Broomfield Road":  [OverpassWay("Broomfield Road",  51.751, -0.341)],
                "Partridge Avenue": [OverpassWay("Partridge Avenue", 51.752, -0.339)],
            },
            queried=["Broomfield Road", "Partridge Avenue"],
        )

        with patch.object(ocr_pipeline, "fetch_image", return_value=object()), \
             patch.object(ocr_pipeline, "ocr_image", return_value=fake_ocr), \
             patch.object(ocr_pipeline, "find_geocode", return_value=fake_xref), \
             patch.object(ocr_pipeline, "NominatimStreetClient") as mk_client:
            mk_client.return_value = object()    # value never used, find_geocode is patched

            outcomes = ocr_pipeline.run_batch(db_path=db)

        assert len(outcomes) == 2
        assert all(o.cluster_lat == pytest.approx(51.751) for o in outcomes)

        conn = connect(db)
        try:
            rows = conn.execute("SELECT * FROM routes ORDER BY id").fetchall()
            assert all(r["geocode_source"] == "ocr" for r in rows)
            assert all(r["lat"] == pytest.approx(51.751) for r in rows)
            assert all(r["city"] == "Chelmsford" for r in rows)
            assert all(r["country"] == "United Kingdom" for r in rows)
            assert count_by_geocode_source(conn) == {"ocr": 2}
            # R-tree should have both rows now
            n = conn.execute("SELECT COUNT(*) AS n FROM routes_rtree").fetchone()["n"]
            assert n == 2
        finally:
            conn.close()

    def test_no_streets_marks_attempted_without_lat(self, tmp_path: Path) -> None:
        db = tmp_path / "db.sqlite"
        conn = connect(db)
        upsert_route(conn, Route(title="A", category="cats-dogs",
                                  image_url="http://example/a.jpg",
                                  stravart_url="s", scraped_at="t"))
        conn.commit()
        conn.close()

        empty_ocr = OcrResult(fragments=[], street_candidates=[])
        with patch.object(ocr_pipeline, "fetch_image", return_value=object()), \
             patch.object(ocr_pipeline, "ocr_image", return_value=empty_ocr), \
             patch.object(ocr_pipeline, "NominatimStreetClient"):
            outcomes = ocr_pipeline.run_batch(db_path=db)

        assert len(outcomes) == 1 and outcomes[0].cluster_lat is None

        conn = connect(db)
        try:
            row = conn.execute("SELECT * FROM routes WHERE id=1").fetchone()
            assert row["lat"] is None
            assert row["geocode_source"] == "ocr-failed"
            assert row["ocr_attempted_at"] is not None
        finally:
            conn.close()

    def test_summary_shape(self) -> None:
        out = ocr_pipeline.summary([])
        assert out["attempted"] == 0
        assert out["success_rate"] == 0.0
