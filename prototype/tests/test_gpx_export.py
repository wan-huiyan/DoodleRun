"""Tests that write_gpx produces a valid GPX 1.1 document."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from gpx_export import write_gpx

NS = {"gpx": "http://www.topografix.com/GPX/1/1"}


@pytest.fixture
def points():
    return [(37.7749, -122.4194), (37.7755, -122.4180), (37.7760, -122.4170)]


class TestWriteGpx:
    def test_creates_parseable_xml(self, tmp_path: Path, points):
        out = tmp_path / "r.gpx"
        write_gpx(str(out), points, name="Test", description="d")
        tree = ET.parse(out)
        root = tree.getroot()
        assert root.tag.endswith("}gpx")
        assert root.attrib["version"] == "1.1"
        assert root.attrib["creator"] == "DoodleRun"

    def test_emits_route_and_track_with_correct_counts(self, tmp_path: Path, points):
        out = tmp_path / "r.gpx"
        write_gpx(str(out), points, name="Test")
        root = ET.parse(out).getroot()
        rtepts = root.findall(".//gpx:rte/gpx:rtept", NS)
        trkpts = root.findall(".//gpx:trk/gpx:trkseg/gpx:trkpt", NS)
        assert len(rtepts) == len(points)
        assert len(trkpts) == len(points)

    def test_coordinate_precision_preserved(self, tmp_path: Path, points):
        out = tmp_path / "r.gpx"
        write_gpx(str(out), points, name="Test")
        root = ET.parse(out).getroot()
        first = root.findall(".//gpx:rte/gpx:rtept", NS)[0]
        assert float(first.attrib["lat"]) == pytest.approx(37.7749, abs=1e-5)
        assert float(first.attrib["lon"]) == pytest.approx(-122.4194, abs=1e-5)

    def test_name_xml_escaped(self, tmp_path: Path, points):
        out = tmp_path / "r.gpx"
        write_gpx(str(out), points, name="A & B <c>")
        # If we wrote raw "<c>" it would either break the parse or appear as
        # a child element, not text. Either way ET.parse + reading the name
        # text is the integration check we want.
        root = ET.parse(out).getroot()
        meta_name = root.find(".//gpx:metadata/gpx:name", NS)
        assert meta_name is not None
        assert meta_name.text == "A & B <c>"

    def test_empty_polyline_raises(self, tmp_path: Path):
        out = tmp_path / "r.gpx"
        with pytest.raises(ValueError):
            write_gpx(str(out), [], name="Test")
