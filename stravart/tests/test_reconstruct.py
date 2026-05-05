"""Tests for the end-to-end ``stravart.reconstruct`` orchestrator.

The OCR + Overpass / Nominatim layer is heavyweight; we mock it. The
contour layer + georef + GPX are exercised with synthetic inputs.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import numpy as np
import pytest

from stravart.contour import RouteContour
from stravart.crossref import CrossRefResult, GeocodeCluster, OverpassWay
from stravart.ocr import OcrResult
from stravart.reconstruct import _confidence, _gcps_from_ocr, reconstruct
from stravart.streets import StreetCandidate


# --- _confidence aggregator --------------------------------------------

class TestConfidence:
    def test_perfect_inputs_score_high(self):
        c = _confidence(n_gcps=8, rmse_m=10, mean_ocr_conf=0.9, fidelity_score=0.9)
        assert c > 0.85

    def test_few_gcps_caps_score(self):
        c = _confidence(n_gcps=3, rmse_m=10, mean_ocr_conf=0.9, fidelity_score=0.9)
        # n_gcps=3 → anchor_term=0; geometric mean uses 0.05 floor → low score
        assert c < 0.5

    def test_high_rmse_penalises(self):
        c = _confidence(n_gcps=6, rmse_m=300, mean_ocr_conf=0.9, fidelity_score=0.9)
        assert c < 0.5

    def test_low_fidelity_penalises(self):
        c = _confidence(n_gcps=6, rmse_m=10, mean_ocr_conf=0.9, fidelity_score=0.1)
        # Below the 0.6 ship threshold — fidelity at 0.1 means the snap is wildly wrong.
        assert c < 0.6


# --- _gcps_from_ocr ----------------------------------------------------

class TestGcpsFromOcr:
    def _ocr_result(self, fragments_with_boxes):
        """Build an OcrResult with parallel fragment_boxes + a derived
        street_candidates list (raw=lower, normalized as Title Case)."""
        from stravart.streets import parse_street
        fragments = [(text, conf) for text, conf, _ in fragments_with_boxes]
        boxes = [box for _, _, box in fragments_with_boxes]
        cands = []
        for text, conf in fragments:
            c = parse_street(text, conf)
            if c is not None:
                cands.append(c)
        # de-dup by normalized name keeping highest confidence
        by_norm = {}
        for c in cands:
            key = c.normalized.lower()
            if key not in by_norm or c.confidence > by_norm[key].confidence:
                by_norm[key] = c
        return OcrResult(
            fragments=fragments,
            street_candidates=sorted(by_norm.values(), key=lambda c: -c.confidence),
            fragment_boxes=boxes,
        )

    def test_builds_gcps_for_in_cluster_streets(self):
        ocr = self._ocr_result([
            ("Broomfield Rd", 0.85, (100, 100, 50, 12)),
            ("Partridge Ave", 0.80, (300, 200, 60, 12)),
            ("Smith Ln", 0.75, (200, 400, 40, 12)),
        ])
        cluster = GeocodeCluster(
            lat=51.50, lon=-0.10,
            bbox=(51.49, 51.51, -0.11, -0.09),
            streets=["Broomfield Road", "Partridge Avenue", "Smith Lane"],
            n_ways=3, confidence=0.7,
        )
        # Each street has one in-cluster Nominatim hit.
        crossref = CrossRefResult(
            cluster=cluster,
            matches={
                "Broomfield Road": [OverpassWay("Broomfield Road", 51.501, -0.102)],
                "Partridge Avenue": [OverpassWay("Partridge Avenue", 51.503, -0.099)],
                "Smith Lane": [OverpassWay("Smith Lane", 51.499, -0.098)],
            },
        )
        gcps = _gcps_from_ocr(ocr, crossref)
        assert len(gcps) == 3
        labels = {g.label for g in gcps}
        assert {"Broomfield Road", "Partridge Avenue", "Smith Lane"} == labels
        # Pixel anchors come from the bbox centers
        for g in gcps:
            assert g.x_px in (100, 300, 200)

    def test_drops_streets_with_only_out_of_cluster_hits(self):
        ocr = self._ocr_result([
            ("Broomfield Rd", 0.85, (100, 100, 50, 12)),
        ])
        cluster = GeocodeCluster(
            lat=51.50, lon=-0.10,
            bbox=(51.49, 51.51, -0.11, -0.09),
            streets=["Broomfield Road"],
            n_ways=1, confidence=0.5,
        )
        crossref = CrossRefResult(
            cluster=cluster,
            matches={
                "Broomfield Road": [
                    OverpassWay("Broomfield Road", 53.50, -2.20),   # Manchester
                ],
            },
        )
        gcps = _gcps_from_ocr(ocr, crossref)
        assert gcps == []

    def test_no_cluster_returns_empty(self):
        ocr = self._ocr_result([])
        crossref = CrossRefResult(cluster=None, matches={})
        assert _gcps_from_ocr(ocr, crossref) == []


# --- reconstruct (mocked) ----------------------------------------------

def _grid_graph_for_reconstruct(lat0=51.50, lon0=-0.10, *, rows=20, cols=20):
    """A bigger grid graph + EPSG:4326 crs so OSMnx accepts it."""
    import networkx as nx
    g = nx.MultiDiGraph(crs="EPSG:4326")
    spacing = 50.0   # 50 m
    dlat = math.degrees(spacing / 6_371_000.0)
    dlon = math.degrees(spacing / (6_371_000.0 * math.cos(math.radians(lat0))))
    for r in range(rows):
        for c in range(cols):
            g.add_node(r * cols + c, y=lat0 + r * dlat, x=lon0 + c * dlon)
    for r in range(rows):
        for c in range(cols):
            here = r * cols + c
            for dr, dc in [(0, 1), (1, 0)]:
                rr, cc = r + dr, c + dc
                if 0 <= rr < rows and 0 <= cc < cols:
                    other = rr * cols + cc
                    g.add_edge(here, other, length=spacing)
                    g.add_edge(other, here, length=spacing)
    return g


def test_reconstruct_short_circuits_when_contour_empty(tmp_path):
    """Pass an image that has no saturated pixels — the contour stage gives up."""
    blank = np.full((200, 200, 3), 200, dtype=np.uint8)
    with patch("stravart.reconstruct.fetch_image", return_value=blank):
        rec = reconstruct(
            "https://example.com/blank.jpg",
            crossref_client=None,
            download_graph=False,
        )
    assert rec.failure is not None
    assert "contour" in rec.failure


def test_reconstruct_short_circuits_when_no_streets(tmp_path):
    """Image has a route stroke but OCR returns no street candidates."""
    import cv2
    img = np.full((200, 200, 3), 200, dtype=np.uint8)
    cv2.line(img, (10, 100), (190, 100), (0, 0, 220), thickness=4)
    fake_ocr = OcrResult(fragments=[], street_candidates=[], fragment_boxes=[])
    with patch("stravart.reconstruct.fetch_image", return_value=img), \
         patch("stravart.reconstruct.ocr_image", return_value=fake_ocr):
        rec = reconstruct(
            "https://example.com/img.jpg",
            crossref_client=None,
            download_graph=False,
        )
    assert rec.failure is not None
    assert "ocr" in rec.failure


def test_reconstruct_ends_at_mapmatch_when_download_disabled():
    """A successful run that stops at the mapmatch stage (no graph download)."""
    import cv2
    img = np.full((300, 300, 3), 200, dtype=np.uint8)
    cv2.line(img, (50, 50), (250, 250), (0, 0, 220), thickness=4)

    # Fake OCR: return three streets with bbox positions matching a known grid.
    cands = [
        StreetCandidate(raw="Broomfield Rd", normalized="Broomfield Road",
                        suffix="road", confidence=0.85),
        StreetCandidate(raw="Partridge Ave", normalized="Partridge Avenue",
                        suffix="avenue", confidence=0.80),
        StreetCandidate(raw="Smith Ln", normalized="Smith Lane",
                        suffix="lane", confidence=0.75),
    ]
    fragments = [(c.raw, c.confidence) for c in cands]
    boxes = [(80.0, 80.0, 30, 12), (220.0, 80.0, 30, 12), (150.0, 220.0, 30, 12)]
    fake_ocr = OcrResult(
        fragments=fragments, street_candidates=cands, fragment_boxes=boxes,
    )

    cluster = GeocodeCluster(
        lat=51.50, lon=-0.10, bbox=(51.495, 51.505, -0.105, -0.095),
        streets=[c.normalized for c in cands], n_ways=3, confidence=0.7,
    )
    matches = {
        "Broomfield Road": [OverpassWay("Broomfield Road", 51.498, -0.103)],
        "Partridge Avenue": [OverpassWay("Partridge Avenue", 51.498, -0.097)],
        "Smith Lane":      [OverpassWay("Smith Lane",      51.502, -0.100)],
    }
    fake_xref = CrossRefResult(cluster=cluster, matches=matches)

    with patch("stravart.reconstruct.fetch_image", return_value=img), \
         patch("stravart.reconstruct.ocr_image", return_value=fake_ocr), \
         patch("stravart.reconstruct.find_geocode", return_value=fake_xref):
        rec = reconstruct(
            "https://example.com/img.jpg",
            crossref_client=None,
            download_graph=False,
        )
    # Stages that ran successfully:
    assert rec.contour is not None and rec.contour.polyline
    assert rec.ocr is not None
    assert rec.crossref is not None
    assert rec.georectification is not None
    assert rec.geo_polyline is not None and len(rec.geo_polyline) > 0
    # We deliberately stopped before mapmatch
    assert rec.matched is None
    assert "mapmatch: skipped" in (rec.failure or "")


def test_reconstruct_full_path_with_mock_graph(tmp_path):
    """Wire through to a successful GPX with a synthetic graph injected."""
    import cv2
    img = np.full((300, 300, 3), 200, dtype=np.uint8)
    cv2.line(img, (50, 50), (250, 250), (0, 0, 220), thickness=4)

    cands = [
        StreetCandidate(raw="Broomfield Rd", normalized="Broomfield Road",
                        suffix="road", confidence=0.85),
        StreetCandidate(raw="Partridge Ave", normalized="Partridge Avenue",
                        suffix="avenue", confidence=0.85),
        StreetCandidate(raw="Smith Ln", normalized="Smith Lane",
                        suffix="lane", confidence=0.85),
        StreetCandidate(raw="High St", normalized="High Street",
                        suffix="street", confidence=0.85),
    ]
    fragments = [(c.raw, c.confidence) for c in cands]
    boxes = [(80.0, 80.0, 30, 12), (220.0, 80.0, 30, 12),
             (150.0, 220.0, 30, 12), (80.0, 220.0, 30, 12)]
    fake_ocr = OcrResult(fragments=fragments, street_candidates=cands, fragment_boxes=boxes)

    # Place the streets so a 50 m grid step at (51.50, -0.10) keeps the
    # GCPs ~aligned with the image-pixel anchors (linear-ish transform).
    lat0, lon0 = 51.50, -0.10
    spacing = 50.0
    dlat = math.degrees(spacing / 6_371_000.0)
    dlon = math.degrees(spacing / (6_371_000.0 * math.cos(math.radians(lat0))))
    cluster = GeocodeCluster(
        lat=lat0, lon=lon0,
        bbox=(lat0 - 10 * dlat, lat0 + 10 * dlat,
              lon0 - 10 * dlon, lon0 + 10 * dlon),
        streets=[c.normalized for c in cands], n_ways=4, confidence=0.7,
    )
    # The synthetic mapping: pixel (x, y) → (lat0 + (rows-1-y/30)*dlat,
    #                                         lon0 + (x/30 - 5)*dlon)
    # i.e. 1 pixel = ~5/3 metres, with image y growing downward.
    def _pix_to_geo(px, py):
        return (
            lat0 + (5 - py / 30.0) * dlat,
            lon0 + (px / 30.0 - 5.0) * dlon,
        )
    matches = {}
    for c, (px, py, _, _) in zip(cands, boxes):
        lat, lon = _pix_to_geo(px, py)
        matches[c.normalized] = [OverpassWay(c.normalized, lat, lon)]
    fake_xref = CrossRefResult(cluster=cluster, matches=matches)

    g = _grid_graph_for_reconstruct(lat0=lat0 - 10 * dlat, lon0=lon0 - 10 * dlon,
                                    rows=20, cols=20)

    with patch("stravart.reconstruct.fetch_image", return_value=img), \
         patch("stravart.reconstruct.ocr_image", return_value=fake_ocr), \
         patch("stravart.reconstruct.find_geocode", return_value=fake_xref), \
         patch("stravart.reconstruct.load_graph", return_value=g):
        rec = reconstruct(
            "https://example.com/img.jpg",
            crossref_client=None,
            download_graph=True,
            min_confidence=0.0,        # we want the GPX even if score is borderline
        )
    assert rec.failure is None or "confidence" not in rec.failure
    assert rec.matched is not None
    assert rec.fidelity is not None
    if rec.confidence > 0.0:
        assert rec.gpx_xml is not None
        assert rec.gpx_xml.startswith("<?xml")
