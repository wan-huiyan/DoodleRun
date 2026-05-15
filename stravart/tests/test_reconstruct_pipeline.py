"""Tests for the Phase 3 batch driver + DB schema migration."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from stravart.db import (
    Route, connect, count_reconstructions,
    routes_needing_reconstruction, update_reconstruction, upsert_route,
)
from stravart.reconstruct import Reconstruction
from stravart.reconstruct_pipeline import (
    ReconstructionOutcome, run_batch, summary,
)


# --- DB schema migration ----------------------------------------------

def _seed_route(conn: sqlite3.Connection, **overrides) -> int:
    base = dict(
        title="DOG", category="cats-dogs",
        image_url="https://example.com/img.jpg",
        stravart_url="https://strav.art/dog",
        scraped_at="2026-01-01T00:00:00Z",
        lat=51.50, lon=-0.10, geocode_confidence=0.7, geocode_source="ocr",
    )
    base.update(overrides)
    return upsert_route(conn, Route(**base))


class TestSchemaMigration:
    def test_phase3_columns_added_on_connect(self, tmp_path):
        conn = connect(tmp_path / "test.sqlite")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(routes)")}
        assert "gpx_path" in cols
        assert "reconstruction_confidence" in cols
        assert "reconstruction_attempted_at" in cols
        assert "reconstruction_failure" in cols

    def test_phase4b_columns_added_on_connect(self, tmp_path):
        """Phase 4b adds reconstruction_kind + reconstruction_review_status."""
        conn = connect(tmp_path / "test.sqlite")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(routes)")}
        assert "reconstruction_kind" in cols
        assert "reconstruction_review_status" in cols

    def test_existing_phase2_db_migrates_in_place(self, tmp_path):
        # Build a Phase 2-shaped DB by hand (no Phase 3 columns).
        db = tmp_path / "phase2.sqlite"
        c = sqlite3.connect(db)
        c.execute("""
            CREATE TABLE routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT, city TEXT, country TEXT,
                lat REAL, lon REAL,
                geocode_confidence REAL NOT NULL DEFAULT 0.0,
                geocode_source TEXT NOT NULL DEFAULT 'title',
                ocr_streets TEXT, ocr_attempted_at TEXT,
                image_url TEXT NOT NULL,
                stravart_url TEXT NOT NULL,
                distance_estimate_km REAL,
                scraped_at TEXT NOT NULL,
                UNIQUE(image_url)
            );
        """)
        c.execute("""INSERT INTO routes
            (title, category, image_url, stravart_url, scraped_at)
            VALUES ('OLD', 'cats-dogs', 'a', 'b', '2026-01-01')""")
        c.commit()
        c.close()

        # Re-open via connect() — should add the new columns + keep old data
        conn = connect(db)
        rows = list(conn.execute("SELECT title, gpx_path FROM routes"))
        assert len(rows) == 1
        assert rows[0]["title"] == "OLD"
        assert rows[0]["gpx_path"] is None


# --- routes_needing_reconstruction -----------------------------------

class TestRoutesNeedingReconstruction:
    def test_only_geocoded_routes_returned(self, tmp_path):
        conn = connect(tmp_path / "t.sqlite")
        # geocoded
        _seed_route(conn, title="A", image_url="a")
        # not geocoded
        _seed_route(conn, title="B", image_url="b", lat=None, lon=None)
        conn.commit()
        rows = routes_needing_reconstruction(conn)
        assert {r["title"] for r in rows} == {"A"}

    def test_skips_already_attempted(self, tmp_path):
        conn = connect(tmp_path / "t.sqlite")
        rid = _seed_route(conn, title="A", image_url="a")
        with conn:
            update_reconstruction(
                conn, rid, gpx_path=None, confidence=0.0,
                attempted_at="2026-05-01T00:00:00Z",
                failure="contour: empty",
            )
        rows = routes_needing_reconstruction(conn)
        assert rows == []

    def test_retry_attempted_picks_up_failed_rows(self, tmp_path):
        conn = connect(tmp_path / "t.sqlite")
        rid = _seed_route(conn, title="A", image_url="a")
        with conn:
            update_reconstruction(
                conn, rid, gpx_path=None, confidence=0.0,
                attempted_at="2026-05-01T00:00:00Z",
                failure="contour: empty",
            )
        rows = routes_needing_reconstruction(conn, retry_attempted=True)
        assert len(rows) == 1


# --- run_batch (integration with mocked reconstruct) ------------------

class TestRunBatch:
    def test_writes_gpx_when_confidence_clears(self, tmp_path):
        db = tmp_path / "stravart.sqlite"
        conn = connect(db)
        rid = _seed_route(conn, title="DOG", image_url="https://x/img.jpg")
        conn.commit()
        conn.close()

        # Mock reconstruct() to return a Reconstruction with a known gpx
        success = Reconstruction(
            image_url="https://x/img.jpg",
            confidence=0.75,
            gpx_xml="<?xml version='1.0'?><gpx></gpx>",
        )
        with patch("stravart.reconstruct_pipeline.reconstruct", return_value=success):
            outcomes = run_batch(db, crossref_cache=tmp_path / "cache.json")
        assert len(outcomes) == 1
        o = outcomes[0]
        assert o.gpx_path is not None
        assert o.confidence == 0.75
        assert (tmp_path / "gpx" / f"route_{rid:05d}.gpx").exists()

        conn = connect(db)
        try:
            row = conn.execute("SELECT * FROM routes WHERE id = ?", (rid,)).fetchone()
        finally:
            conn.close()
        assert row["gpx_path"] is not None
        assert row["reconstruction_attempted_at"] is not None
        assert row["reconstruction_confidence"] == pytest.approx(0.75)
        assert row["reconstruction_failure"] is None

    def test_records_failure_without_writing_gpx(self, tmp_path):
        db = tmp_path / "stravart.sqlite"
        conn = connect(db)
        _seed_route(conn, title="DOG", image_url="https://x/img.jpg")
        conn.commit()
        conn.close()

        failure = Reconstruction(
            image_url="https://x/img.jpg",
            failure="contour: empty",
            confidence=0.0,
        )
        with patch("stravart.reconstruct_pipeline.reconstruct", return_value=failure):
            outcomes = run_batch(db, crossref_cache=tmp_path / "cache.json")
        assert outcomes[0].gpx_path is None
        assert "contour" in outcomes[0].failure
        # No gpx file produced
        assert not list(tmp_path.glob("gpx/*.gpx"))

    def test_records_kind_and_review_status_on_ship(self, tmp_path):
        """Phase 4b: pipeline persists ``kind`` + ``review_status`` to the DB."""
        db = tmp_path / "stravart.sqlite"
        conn = connect(db)
        rid = _seed_route(conn, title="DOG", image_url="https://x/img.jpg")
        conn.commit()
        conn.close()

        success = Reconstruction(
            image_url="https://x/img.jpg",
            confidence=0.55, gpx_xml="<?xml ?><gpx></gpx>",
            kind="street", review_status="review",
        )
        with patch("stravart.reconstruct_pipeline.reconstruct", return_value=success):
            outcomes = run_batch(db, crossref_cache=tmp_path / "cache.json")
        o = outcomes[0]
        assert o.kind == "street"
        assert o.review_status == "review"
        conn = connect(db)
        try:
            row = conn.execute("SELECT * FROM routes WHERE id = ?", (rid,)).fetchone()
        finally:
            conn.close()
        assert row["reconstruction_kind"] == "street"
        assert row["reconstruction_review_status"] == "review"

    def test_city_scale_kind_persists(self, tmp_path):
        """City-scale outputs persist with kind='city-scale', review_status='review'."""
        db = tmp_path / "stravart.sqlite"
        conn = connect(db)
        rid = _seed_route(conn, title="MUNICH LION", image_url="https://x/img.jpg")
        conn.commit()
        conn.close()

        success = Reconstruction(
            image_url="https://x/img.jpg",
            confidence=0.35, gpx_xml="<?xml ?><gpx></gpx>",
            kind="city-scale", review_status="review",
        )
        with patch("stravart.reconstruct_pipeline.reconstruct", return_value=success):
            outcomes = run_batch(db, crossref_cache=tmp_path / "cache.json")
        assert outcomes[0].kind == "city-scale"
        conn = connect(db)
        try:
            row = conn.execute("SELECT * FROM routes WHERE id = ?", (rid,)).fetchone()
        finally:
            conn.close()
        assert row["reconstruction_kind"] == "city-scale"

    def test_passes_title_latlon_to_reconstruct(self, tmp_path):
        """run_batch should forward the row's lat/lon into reconstruct()."""
        db = tmp_path / "stravart.sqlite"
        conn = connect(db)
        _seed_route(conn, title="BERLIN MUTT", image_url="https://x/img.jpg",
                    lat=52.52, lon=13.405, geocode_confidence=0.8)
        conn.commit()
        conn.close()

        captured: dict = {}
        def _spy(image_url, **kwargs):
            captured.update(kwargs)
            return Reconstruction(image_url=image_url, confidence=0.0,
                                  failure="ocr: no street candidates")
        with patch("stravart.reconstruct_pipeline.reconstruct", side_effect=_spy):
            run_batch(db, crossref_cache=tmp_path / "cache.json")
        assert captured["title_latlon"] == (52.52, 13.405)
        assert captured["title_confidence"] == pytest.approx(0.8)
        assert captured["min_gcps"] == 5   # Phase 4b default

    def test_disable_city_scale_fallback_skips_title_latlon(self, tmp_path):
        """``enable_city_scale_fallback=False`` clears title_latlon → legacy path."""
        db = tmp_path / "stravart.sqlite"
        conn = connect(db)
        _seed_route(conn, title="BERLIN MUTT", image_url="https://x/img.jpg",
                    lat=52.52, lon=13.405)
        conn.commit()
        conn.close()

        captured: dict = {}
        def _spy(image_url, **kwargs):
            captured.update(kwargs)
            return Reconstruction(image_url=image_url, confidence=0.0,
                                  failure="ocr: no street candidates")
        with patch("stravart.reconstruct_pipeline.reconstruct", side_effect=_spy):
            run_batch(db, crossref_cache=tmp_path / "cache.json",
                      enable_city_scale_fallback=False)
        assert captured["title_latlon"] is None

    def test_orchestrator_exception_swallowed_into_outcome(self, tmp_path):
        db = tmp_path / "stravart.sqlite"
        conn = connect(db)
        _seed_route(conn, title="DOG", image_url="https://x/img.jpg")
        conn.commit()
        conn.close()

        with patch("stravart.reconstruct_pipeline.reconstruct",
                   side_effect=RuntimeError("boom")):
            outcomes = run_batch(db, crossref_cache=tmp_path / "cache.json")
        assert outcomes[0].gpx_path is None
        assert "orchestrator" in (outcomes[0].failure or "")


# --- summary ----------------------------------------------------------

class TestSummary:
    def test_groups_failures_by_stage(self):
        outs = [
            ReconstructionOutcome(1, "A", "u", 0.7, None, "gpx/1.gpx", 5, 0.8),
            ReconstructionOutcome(2, "B", "u", 0.0, "contour: empty", None, 0, None),
            ReconstructionOutcome(3, "C", "u", 0.0, "contour: too short", None, 0, None),
            ReconstructionOutcome(4, "D", "u", 0.0, "ocr: no streets", None, 0, None),
        ]
        s = summary(outs)
        assert s["attempted"] == 4
        assert s["shipped"] == 1
        assert s["failure_modes"]["contour"] == 2
        assert s["failure_modes"]["ocr"] == 1
        assert s["mean_confidence"] == pytest.approx(0.175, abs=0.01)

    def test_empty(self):
        assert summary([]) == {"attempted": 0, "shipped": 0}

    def test_groups_by_kind_and_review_status(self):
        """Phase 4b summary breaks shipped down by kind + review tier."""
        outs = [
            ReconstructionOutcome(1, "marathon", "u", 0.72, None, "gpx/1.gpx", 6, 0.45,
                                  kind="street", review_status="shipped"),
            ReconstructionOutcome(2, "review-tier", "u", 0.50, None, "gpx/2.gpx", 5, 0.30,
                                  kind="street", review_status="review"),
            ReconstructionOutcome(3, "berlin mutt", "u", 0.35, None, "gpx/3.gpx", 0, None,
                                  kind="city-scale", review_status="review"),
            ReconstructionOutcome(4, "failed", "u", 0.0, "ocr: no streets", None, 0, None),
        ]
        s = summary(outs)
        assert s["shipped"] == 3
        assert s["by_kind"] == {"street": 2, "city-scale": 1}
        assert s["by_review_status"] == {"shipped": 1, "review": 2}
