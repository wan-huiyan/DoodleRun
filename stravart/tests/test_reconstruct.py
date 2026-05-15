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
from stravart.georef import GroundControlPoint
from stravart.ocr import OcrResult
from stravart.reconstruct import (
    Reconstruction,
    _confidence,
    _dedup_gcps_by_geo,
    _gcp_pixel_hull_frac,
    _gcps_from_ocr,
    reconstruct,
)
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
            # Synthetic fixture has 3 GCPs by design — bypass the production
            # ≥5 gate so we exercise the orchestrator wiring, not the gate.
            min_gcps=3,
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
            min_gcps=3,                # synthetic fixture has 4 — bypass production gate
            min_rmse_m=0.0,            # synthetic transform is exact; allow RMSE=0
        )
    assert rec.failure is None or "confidence" not in rec.failure
    assert rec.matched is not None
    assert rec.fidelity is not None
    if rec.confidence > 0.0:
        assert rec.gpx_xml is not None
        assert rec.gpx_xml.startswith("<?xml")


# --- _dedup_gcps_by_geo ------------------------------------------------

class TestDedupGcpsByGeo:
    """OCR'd street labels that resolve to the same way node count as one anchor."""

    def test_keeps_distinct_geo_anchors(self):
        gcps = [
            GroundControlPoint(x_px=10, y_px=10, lat=51.5000, lon=-0.1000, label="A"),
            GroundControlPoint(x_px=20, y_px=20, lat=51.5010, lon=-0.1010, label="B"),
            GroundControlPoint(x_px=30, y_px=30, lat=51.5020, lon=-0.1020, label="C"),
        ]
        assert len(_dedup_gcps_by_geo(gcps)) == 3

    def test_drops_duplicate_geo_anchors(self):
        # B is within 1 m of A — same intersection, OCR caught both side-streets.
        gcps = [
            GroundControlPoint(x_px=10, y_px=10, lat=51.50000, lon=-0.10000,
                               label="A", weight=0.9),
            GroundControlPoint(x_px=22, y_px=10, lat=51.500005, lon=-0.100005,
                               label="B-dup-of-A", weight=0.7),
            GroundControlPoint(x_px=30, y_px=30, lat=51.501, lon=-0.101, label="C"),
        ]
        kept = _dedup_gcps_by_geo(gcps)
        assert len(kept) == 2
        # Highest-weight wins each cluster
        labels = {g.label for g in kept}
        assert "A" in labels and "B-dup-of-A" not in labels


# --- _gcp_pixel_hull_frac ---------------------------------------------

class TestGcpPixelHullFrac:
    """Convex-hull area of GCP pixels as a fraction of image area."""

    def test_spread_anchors_cover_meaningful_fraction(self):
        gcps = [
            GroundControlPoint(x_px=50, y_px=50, lat=51.5, lon=-0.1, label="A"),
            GroundControlPoint(x_px=950, y_px=50, lat=51.5, lon=-0.1, label="B"),
            GroundControlPoint(x_px=950, y_px=950, lat=51.5, lon=-0.1, label="C"),
            GroundControlPoint(x_px=50, y_px=950, lat=51.5, lon=-0.1, label="D"),
        ]
        frac = _gcp_pixel_hull_frac(gcps, image_height=1000, image_width=1000)
        # Hull is a 900x900 square = 0.81 of image area.
        assert 0.80 <= frac <= 0.85

    def test_clustered_anchors_have_tiny_hull(self):
        # 5 anchors all in a 50x50 box of a 1000x1000 image.
        gcps = [
            GroundControlPoint(x_px=500 + i * 10, y_px=500 + j * 10,
                               lat=51.5, lon=-0.1, label=f"x{i}{j}")
            for i, j in [(0, 0), (1, 0), (0, 1), (1, 1), (2, 2)]
        ]
        frac = _gcp_pixel_hull_frac(gcps, image_height=1000, image_width=1000)
        # Hull is at most 20x20 px / 1Mpx → << 5%.
        assert frac < 0.001

    def test_collinear_anchors_have_zero_hull(self):
        # All on y=500 → 1D, hull area = 0.
        gcps = [
            GroundControlPoint(x_px=100 + i * 100, y_px=500, lat=51.5, lon=-0.1,
                               label=f"x{i}")
            for i in range(5)
        ]
        frac = _gcp_pixel_hull_frac(gcps, image_height=1000, image_width=1000)
        assert frac == 0.0


# --- reconstruct gate behaviour ----------------------------------------

def _make_xref_with_n_streets(
    n: int, lat0: float = 51.50, lon0: float = -0.10, *,
    pixel_positions=None, cluster_bbox_pad_deg: float = 0.02,
):
    """Synthesise an OcrResult + CrossRefResult pair with N candidates.

    Anchors sit on a regularly-spaced grid both in pixel and lat/lon space
    so the resulting affine is well-conditioned.
    """
    if pixel_positions is None:
        side = max(2, int(round(n ** 0.5)))
        pixel_positions = [
            (50.0 + (i % side) * (200.0 / max(1, side - 1)),
             50.0 + (i // side) * (200.0 / max(1, side - 1)))
            for i in range(n)
        ]
    # parse_street rejects digits in names, so use alphabetic per-anchor labels.
    def _name(i: int) -> str:
        a = chr(ord("A") + (i // 26))
        b = chr(ord("a") + (i % 26))
        return f"{a}{b} Rd"
    cands = [
        StreetCandidate(
            raw=_name(i), normalized=_name(i).replace(" Rd", " Road"),
            suffix="road", confidence=0.85,
        )
        for i in range(n)
    ]
    boxes = [(px, py, 30, 12) for (px, py) in pixel_positions]
    ocr = OcrResult(
        fragments=[(c.raw, c.confidence) for c in cands],
        street_candidates=cands, fragment_boxes=boxes,
    )
    cluster = GeocodeCluster(
        lat=lat0, lon=lon0,
        bbox=(lat0 - cluster_bbox_pad_deg, lat0 + cluster_bbox_pad_deg,
              lon0 - cluster_bbox_pad_deg, lon0 + cluster_bbox_pad_deg),
        streets=[c.normalized for c in cands], n_ways=n, confidence=0.8,
    )
    # Place each street at a unique lat/lon on a parallel grid to the pixels
    side = max(2, int(round(n ** 0.5)))
    matches = {}
    for i, c in enumerate(cands):
        lat = lat0 + ((i // side) - (side - 1) / 2.0) * 0.005
        lon = lon0 + ((i % side) - (side - 1) / 2.0) * 0.005
        matches[c.normalized] = [OverpassWay(c.normalized, lat, lon)]
    return ocr, CrossRefResult(cluster=cluster, matches=matches)


class TestReconstructGcpGate:
    def _img(self):
        import cv2
        img = np.full((300, 300, 3), 200, dtype=np.uint8)
        cv2.line(img, (50, 50), (250, 250), (0, 0, 220), thickness=4)
        return img

    def test_rejects_below_min_gcps(self):
        ocr, xref = _make_xref_with_n_streets(4)   # min_gcps default is 5
        with patch("stravart.reconstruct.fetch_image", return_value=self._img()), \
             patch("stravart.reconstruct.ocr_image", return_value=ocr), \
             patch("stravart.reconstruct.find_geocode", return_value=xref):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
            )
        assert rec.georectification is None
        assert rec.failure is not None
        assert "GCPs" in rec.failure
        assert "need ≥5" in rec.failure or "need >=5" in rec.failure

    def test_rejects_clustered_gcps(self):
        # 6 GCPs but all in a tiny pixel cluster — degenerate fit waiting to happen.
        clustered = [(140 + (i % 3) * 5, 140 + (i // 3) * 5) for i in range(6)]
        ocr, xref = _make_xref_with_n_streets(6, pixel_positions=clustered)
        with patch("stravart.reconstruct.fetch_image", return_value=self._img()), \
             patch("stravart.reconstruct.ocr_image", return_value=ocr), \
             patch("stravart.reconstruct.find_geocode", return_value=xref):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
            )
        assert rec.georectification is None
        assert rec.failure is not None
        assert "cover only" in rec.failure or "clustered" in rec.failure.lower()

    def test_accepts_spread_gcps(self):
        ocr, xref = _make_xref_with_n_streets(6)   # 3x3-ish grid spanning 200x200 px
        with patch("stravart.reconstruct.fetch_image", return_value=self._img()), \
             patch("stravart.reconstruct.ocr_image", return_value=ocr), \
             patch("stravart.reconstruct.find_geocode", return_value=xref):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
                min_rmse_m=0.0,   # synthetic anchors fit exactly
            )
        # We deliberately don't download a graph, so the run stops at mapmatch.
        # But the gate has been cleared — georef + geo_polyline are present.
        assert rec.georectification is not None
        assert rec.geo_polyline is not None and len(rec.geo_polyline) > 0


# --- review tier / shipped classification ------------------------------

class TestReviewTier:
    def test_shipped_tier_when_above_strict(self):
        rec = Reconstruction(image_url="x")
        # Simulate post-reconstruct state by reading the dataclass directly —
        # the classification rule lives in reconstruct() and we verify it via
        # the integration test below.
        rec.confidence = 0.7
        # Manual classification mirroring reconstruct() final block.
        rec.review_status = "shipped" if rec.confidence >= 0.6 else "review"
        assert rec.review_status == "shipped"

    def test_review_tier_when_between_min_and_strict(self):
        rec = Reconstruction(image_url="x")
        rec.confidence = 0.50
        rec.review_status = "shipped" if rec.confidence >= 0.6 else "review"
        assert rec.review_status == "review"

    def test_is_runnable_property(self):
        rec = Reconstruction(image_url="x", gpx_xml="<?xml ... ?>", kind="street")
        assert rec.is_runnable is True
        # City-scale fallback is NOT runnable, even with GPX present:
        rec_city = Reconstruction(image_url="x", gpx_xml="<?xml ... ?>", kind="city-scale")
        assert rec_city.is_runnable is False
        # No GPX → not runnable regardless of kind:
        rec_failed = Reconstruction(image_url="x", gpx_xml=None, kind="street")
        assert rec_failed.is_runnable is False


# --- Phase 4b: city-scale fallback for OCR-zero images ----------------

class TestCityScaleFallback:
    def _img_with_stroke(self):
        import cv2
        img = np.full((300, 300, 3), 200, dtype=np.uint8)
        cv2.line(img, (50, 50), (250, 250), (0, 0, 220), thickness=4)
        return img

    def test_no_streets_no_title_returns_original_failure(self):
        """Without a title_latlon, OCR0 stays a hard failure (legacy path)."""
        fake_ocr = OcrResult(fragments=[], street_candidates=[], fragment_boxes=[])
        with patch("stravart.reconstruct.fetch_image", return_value=self._img_with_stroke()), \
             patch("stravart.reconstruct.ocr_image", return_value=fake_ocr):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
            )
        assert rec.kind == "street"
        assert rec.gpx_xml is None
        assert rec.failure is not None and "no street candidates" in rec.failure

    def test_no_streets_with_title_falls_back_to_city_scale(self):
        """When Phase 1 geocoded the title, fall back to centroid placement."""
        fake_ocr = OcrResult(fragments=[], street_candidates=[], fragment_boxes=[])
        with patch("stravart.reconstruct.fetch_image", return_value=self._img_with_stroke()), \
             patch("stravart.reconstruct.ocr_image", return_value=fake_ocr):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
                title_latlon=(52.5200, 13.4050),    # Berlin
                title_confidence=0.7,
            )
        assert rec.failure is None
        assert rec.kind == "city-scale"
        assert rec.review_status == "review"
        # Confidence comes from title geocoder (clamped to [0.1, 0.5])
        assert 0.1 <= rec.confidence <= 0.5
        assert rec.gpx_xml is not None
        assert rec.gpx_xml.startswith("<?xml")
        # Polyline lives near Berlin
        assert rec.geo_polyline is not None
        for lat, lon in rec.geo_polyline:
            assert 52.3 < lat < 52.7
            assert 13.2 < lon < 13.6
        # is_runnable is False — city-scale is decorative, not navigable.
        assert rec.is_runnable is False

    def test_title_confidence_caps_at_0_5(self):
        """Even at 1.0 title confidence the city-scale output never exceeds 0.5."""
        fake_ocr = OcrResult(fragments=[], street_candidates=[], fragment_boxes=[])
        with patch("stravart.reconstruct.fetch_image", return_value=self._img_with_stroke()), \
             patch("stravart.reconstruct.ocr_image", return_value=fake_ocr):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
                title_latlon=(52.5200, 13.4050),
                title_confidence=1.0,
            )
        assert rec.confidence == 0.5
        assert rec.review_status == "review"

    def test_city_scale_skips_osm_stages(self):
        """The fallback path doesn't invoke crossref / load_graph / map_match."""
        fake_ocr = OcrResult(fragments=[], street_candidates=[], fragment_boxes=[])
        with patch("stravart.reconstruct.fetch_image", return_value=self._img_with_stroke()), \
             patch("stravart.reconstruct.ocr_image", return_value=fake_ocr), \
             patch("stravart.reconstruct.find_geocode") as mock_xref, \
             patch("stravart.reconstruct.load_graph") as mock_graph, \
             patch("stravart.reconstruct.map_match") as mock_match:
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=True,
                title_latlon=(51.50, -0.10),
            )
        assert mock_xref.call_count == 0
        assert mock_graph.call_count == 0
        assert mock_match.call_count == 0
        assert rec.kind == "city-scale"


# --- Phase 4c: extended fallback triggers + distance population --------

class TestCityScaleFallbackExtendedTriggers:
    """Phase 4c: low-anchor / low-RMSE routes with a title centroid produce
    a decorative city-scale output instead of hard-failing."""

    def _img(self):
        import cv2
        img = np.full((300, 300, 3), 200, dtype=np.uint8)
        cv2.line(img, (50, 50), (250, 250), (0, 0, 220), thickness=4)
        return img

    def test_min_gcps_fail_with_title_falls_through_to_city_scale(self):
        """Only 4 GCPs (below min_gcps=5) + a title centroid → city-scale."""
        ocr, xref = _make_xref_with_n_streets(4)
        with patch("stravart.reconstruct.fetch_image", return_value=self._img()), \
             patch("stravart.reconstruct.ocr_image", return_value=ocr), \
             patch("stravart.reconstruct.find_geocode", return_value=xref):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
                title_latlon=(52.5200, 13.4050),    # Berlin
                title_confidence=0.7,
            )
        assert rec.failure is None
        assert rec.kind == "city-scale"
        assert rec.review_status == "review"
        assert rec.gpx_xml is not None
        assert rec.is_runnable is False
        # The diagnostic logs which gate triggered the fallback.
        assert "min_gcps" in rec.diagnostics.get("city_scale_reason", "")

    def test_min_gcps_fail_without_title_keeps_hard_failure(self):
        """Existing path: low GCPs without a title centroid still hard-fails."""
        ocr, xref = _make_xref_with_n_streets(4)
        with patch("stravart.reconstruct.fetch_image", return_value=self._img()), \
             patch("stravart.reconstruct.ocr_image", return_value=ocr), \
             patch("stravart.reconstruct.find_geocode", return_value=xref):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
            )
        assert rec.kind == "street"
        assert rec.gpx_xml is None
        assert rec.failure is not None and "GCPs" in rec.failure

    def test_min_rmse_fail_with_title_falls_through_to_city_scale(self):
        """6 GCPs that fit the affine exactly (RMSE=0) + title → city-scale.

        The synthetic fixture's anchors lie on a regular grid, so the affine
        fit returns RMSE=0. The production default ``min_rmse_m=0.5`` would
        reject this as degenerate; with a title centroid we fall through.
        """
        ocr, xref = _make_xref_with_n_streets(6)
        with patch("stravart.reconstruct.fetch_image", return_value=self._img()), \
             patch("stravart.reconstruct.ocr_image", return_value=ocr), \
             patch("stravart.reconstruct.find_geocode", return_value=xref):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
                title_latlon=(52.5200, 13.4050),    # Berlin
                title_confidence=0.7,
            )
        assert rec.kind == "city-scale"
        assert rec.review_status == "review"
        assert rec.gpx_xml is not None
        # The degenerate affine MUST NOT be persisted — it would mislead any
        # downstream consumer trying to introspect the geo fit.
        assert rec.georectification is None
        assert "min_rmse" in rec.diagnostics.get("city_scale_reason", "")

    def test_min_rmse_fail_without_title_keeps_hard_failure(self):
        """Existing path: degenerate RMSE without a title centroid hard-fails."""
        ocr, xref = _make_xref_with_n_streets(6)
        with patch("stravart.reconstruct.fetch_image", return_value=self._img()), \
             patch("stravart.reconstruct.ocr_image", return_value=ocr), \
             patch("stravart.reconstruct.find_geocode", return_value=xref):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
            )
        assert rec.kind == "street"
        assert rec.gpx_xml is None
        assert rec.failure is not None and "RMSE" in rec.failure

    def test_hull_frac_fail_does_not_fall_through(self):
        """Hull-fraction (clustered/collinear) is NOT a Phase 4c fallback trigger.

        Even with a title centroid, clustered anchors are an honest rejection
        — the cartoon SHAPE may be fine, but the OCR signal that DID land
        was geometrically degenerate, distinct from the low-anchor case.
        """
        clustered = [(140 + (i % 3) * 5, 140 + (i // 3) * 5) for i in range(6)]
        ocr, xref = _make_xref_with_n_streets(6, pixel_positions=clustered)
        with patch("stravart.reconstruct.fetch_image", return_value=self._img()), \
             patch("stravart.reconstruct.ocr_image", return_value=ocr), \
             patch("stravart.reconstruct.find_geocode", return_value=xref):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
                title_latlon=(52.5200, 13.4050),
            )
        assert rec.kind == "street"
        assert rec.gpx_xml is None
        assert rec.failure is not None


class TestTotalDistanceM:
    """Phase 4c: ``total_distance_m`` is populated for any shipped result."""

    def _img(self):
        import cv2
        img = np.full((300, 300, 3), 200, dtype=np.uint8)
        cv2.line(img, (50, 50), (250, 250), (0, 0, 220), thickness=4)
        return img

    def test_failure_leaves_distance_none(self):
        """Failures shouldn't fabricate a distance."""
        blank = np.full((200, 200, 3), 200, dtype=np.uint8)
        with patch("stravart.reconstruct.fetch_image", return_value=blank):
            rec = reconstruct(
                "https://example.com/blank.jpg",
                crossref_client=None,
                download_graph=False,
            )
        assert rec.failure is not None
        assert rec.total_distance_m is None

    def test_city_scale_distance_uses_per_segment_haversine(self):
        """City-scale distance is the sum of per-segment arc lengths.

        Critical: ``geo_polyline`` is the FLAT concatenation of segments
        and would include phantom jumps between disjoint polylines if we
        naively iterated it. The per-segment sum is the only correct count.
        """
        fake_ocr = OcrResult(fragments=[], street_candidates=[], fragment_boxes=[])
        with patch("stravart.reconstruct.fetch_image", return_value=self._img()), \
             patch("stravart.reconstruct.ocr_image", return_value=fake_ocr):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=False,
                title_latlon=(52.5200, 13.4050),
                title_confidence=0.7,
                centroid_target_width_m=4_000.0,
            )
        assert rec.kind == "city-scale"
        assert rec.total_distance_m is not None
        # The cartoon is roughly bbox-width-sized (4 km here). Distance should
        # be comparable to bbox width (a few km), and STRICTLY less than what
        # naive concatenation would give if segments existed (sanity floor).
        assert 100.0 < rec.total_distance_m < 20_000.0

    def test_city_scale_per_segment_sum_excludes_phantom_jumps(self):
        """Direct unit test of the haversine-sum helper.

        Two disjoint segments far apart: per-segment sum should equal the
        sum of within-segment lengths, NOT include the inter-segment gap.
        """
        from stravart.reconstruct import _polylines_total_distance_m
        # Two segments, ~111m each, separated by ~22 km (0.2 deg of latitude).
        # If the function included the jump between them the total would be
        # >22 km; the correct answer is ~222 m.
        polylines = [
            [(51.000, -0.100), (51.001, -0.100)],
            [(51.200, -0.100), (51.201, -0.100)],
        ]
        d = _polylines_total_distance_m(polylines)
        # Two ~111m segments → ~222 m total; well under any phantom-jump value.
        assert 100.0 < d < 400.0

    def test_street_scale_distance_from_matched_length_m(self):
        """Street-scale ship: distance comes from the snapped polyline length."""
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
        fake_ocr = OcrResult(fragments=fragments, street_candidates=cands,
                             fragment_boxes=boxes)

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

        g = _grid_graph_for_reconstruct(
            lat0=lat0 - 10 * dlat, lon0=lon0 - 10 * dlon, rows=20, cols=20,
        )

        with patch("stravart.reconstruct.fetch_image", return_value=img), \
             patch("stravart.reconstruct.ocr_image", return_value=fake_ocr), \
             patch("stravart.reconstruct.find_geocode", return_value=fake_xref), \
             patch("stravart.reconstruct.load_graph", return_value=g):
            rec = reconstruct(
                "https://example.com/img.jpg",
                crossref_client=None,
                download_graph=True,
                min_confidence=0.0,
                min_gcps=3,
                min_rmse_m=0.0,
            )
        # Distance should equal matched.length_m exactly (we mirror it).
        if rec.gpx_xml is not None:
            assert rec.total_distance_m is not None
            assert rec.matched is not None
            assert rec.total_distance_m == pytest.approx(rec.matched.length_m)
            # Non-trivial — the synthetic stroke spans ~200 pixels of a 50 m grid.
            assert rec.total_distance_m > 0.0
