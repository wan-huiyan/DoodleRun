"""Tests for ``stravart.gpx_export``: GPX 1.1 serialisation."""

from __future__ import annotations

import gpxpy
import pytest

from stravart.gpx_export import GpxMetadata, build_gpx, write_gpx


class TestBuildGpx:
    def test_round_trip_through_gpxpy_parser(self):
        coords = [(51.5, -0.1), (51.51, -0.1), (51.51, -0.09)]
        xml = build_gpx(coords, metadata=GpxMetadata(
            name="MANCHESTER DOG",
            description="strav.art reconstruction",
            source="stravart-finder",
            keywords=("strav.art", "dog"),
        ))
        # Re-parse and assert structure
        parsed = gpxpy.parse(xml)
        assert len(parsed.routes) == 1
        rte = parsed.routes[0]
        assert rte.name == "MANCHESTER DOG"
        assert len(rte.points) == 3
        assert rte.points[0].latitude == pytest.approx(51.5)
        assert rte.points[-1].longitude == pytest.approx(-0.09)

    def test_skips_invalid_coords(self):
        coords = [(51.5, -0.1), (float("nan"), -0.1), (200.0, 0.0), (51.6, 0.0)]
        xml = build_gpx(coords)
        parsed = gpxpy.parse(xml)
        # Only the two valid points survive
        assert len(parsed.routes[0].points) == 2

    def test_empty_coords_gives_empty_route(self):
        xml = build_gpx([])
        parsed = gpxpy.parse(xml)
        assert len(parsed.routes) == 1
        assert len(parsed.routes[0].points) == 0


class TestWriteGpx:
    def test_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "deep" / "nested" / "route.gpx"
        coords = [(51.5, -0.1), (51.5, -0.09)]
        path = write_gpx(coords, out, metadata=GpxMetadata(name="route"))
        assert path.exists()
        # File can be parsed back
        parsed = gpxpy.parse(path.read_text())
        assert len(parsed.routes[0].points) == 2
