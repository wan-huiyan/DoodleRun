"""Tests that kml_to_string / write_kml produce a valid KML 2.2 document."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from kml_export import kml_to_string, write_kml

NS = {"kml": "http://www.opengis.net/kml/2.2"}


@pytest.fixture
def points():
    # St Albans-ish — three (lat, lon) tuples.
    return [(51.7500, -0.3400), (51.7510, -0.3380), (51.7520, -0.3360)]


class TestKmlToString:
    def test_xml_header_and_root(self, points):
        text = kml_to_string(points, name="Pig Run")
        assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        assert '<kml xmlns="http://www.opengis.net/kml/2.2">' in text

    def test_parses_and_finds_placemark(self, points):
        text = kml_to_string(points)
        root = ET.fromstring(text)
        placemarks = root.findall(".//kml:Placemark", NS)
        assert len(placemarks) == 1

    def test_coordinates_are_lon_lat_alt(self, points):
        text = kml_to_string(points)
        root = ET.fromstring(text)
        coord_el = root.find(".//kml:LineString/kml:coordinates", NS)
        assert coord_el is not None
        triplets = coord_el.text.strip().split()
        assert len(triplets) == 3
        # First triplet: input was (51.75, -0.34) → KML wants "lon,lat,alt"
        # → "-0.340000,51.750000,0".
        lon, lat, alt = triplets[0].split(",")
        assert float(lon) == pytest.approx(-0.34, abs=1e-5)
        assert float(lat) == pytest.approx(51.75, abs=1e-5)
        assert float(alt) == 0.0

    def test_name_xml_escaped(self, points):
        text = kml_to_string(points, name="A & B <c>")
        root = ET.fromstring(text)   # would fail to parse if not escaped
        names = root.findall(".//kml:name", NS)
        # Document/name and Placemark/name both echo the user-supplied name.
        assert any(n.text == "A & B <c>" for n in names)

    def test_route_is_styled(self, points):
        """My Maps and Google Earth respect KML LineStyle — verify we emit
        a referenced style with a width and an AABBGGRR colour."""
        text = kml_to_string(points)
        root = ET.fromstring(text)
        placemark = root.find(".//kml:Placemark", NS)
        style_url = placemark.find("kml:styleUrl", NS).text
        assert style_url.startswith("#")
        style_id = style_url[1:]
        style = root.find(f".//kml:Style[@id='{style_id}']", NS)
        assert style is not None
        line_style = style.find("kml:LineStyle", NS)
        color = line_style.find("kml:color", NS).text
        width = line_style.find("kml:width", NS).text
        # AABBGGRR = 8 hex chars.
        assert len(color) == 8
        assert int(color, 16) >= 0
        assert int(width) > 0

    def test_empty_polyline_raises(self):
        with pytest.raises(ValueError):
            kml_to_string([])


class TestWriteKml:
    def test_writes_file(self, tmp_path: Path, points):
        out = tmp_path / "r.kml"
        write_kml(str(out), points, name="Pig Run")
        assert out.exists()
        text = out.read_text()
        # Round-trip via the parser to ensure file is valid.
        root = ET.fromstring(text)
        assert root.tag.endswith("}kml")
