"""Tests for ``stravart.georef``: pixel ↔ (lat, lon) affine transform."""

from __future__ import annotations

import math

import numpy as np
import pytest

from stravart.georef import (
    GroundControlPoint,
    bbox_of_geocoords,
    fit_affine,
    project_polyline,
)


# ---------- helpers: build a synthetic image-pixel ↔ geo correspondence ---

# Pretend (lat0, lon0) = (51.50, -0.10) is the image centre, and 1 pixel = 1 m
# in both axes (north-up). We then synthesise GCPs by running known pixel
# coords through this transform and asserting the fitter recovers it.
LAT0, LON0 = 51.50, -0.10
PX_PER_M = 1.0


def _geo_at(x_px: float, y_px: float) -> tuple[float, float]:
    """The 'truth' pixel→geo transform for the test fixture."""
    # x_px → eastward metres, y_px → southward metres (image y grows down).
    east_m = x_px / PX_PER_M
    south_m = y_px / PX_PER_M
    # Inverse equirectangular at (LAT0, LON0)
    lat = LAT0 - math.degrees(south_m / 6371000.0)
    lon = LON0 + math.degrees(east_m / (6371000.0 * math.cos(math.radians(LAT0))))
    return lat, lon


def _gcp(x_px, y_px, label: str) -> GroundControlPoint:
    lat, lon = _geo_at(x_px, y_px)
    return GroundControlPoint(x_px=x_px, y_px=y_px, lat=lat, lon=lon, label=label)


# --- fitting -------------------------------------------------------------

class TestFitAffine:
    def test_three_gcps_fit_to_subpixel_accuracy(self):
        gcps = [
            _gcp(100,  50, "A"),
            _gcp(400, 100, "B"),
            _gcp(250, 350, "C"),
        ]
        gr = fit_affine(gcps)
        assert gr.n_anchors == 3
        assert gr.rmse_m < 0.1   # ≪ 1 m for clean inputs
        # Forward-transform each anchor and check it lands on the input lat/lon
        for g in gcps:
            lat, lon = gr.forward(g.x_px, g.y_px)
            assert abs(lat - g.lat) < 1e-6
            assert abs(lon - g.lon) < 1e-6

    def test_inverse_round_trip(self):
        gcps = [
            _gcp(100,  50, "A"),
            _gcp(500, 100, "B"),
            _gcp(250, 400, "C"),
            _gcp(450, 450, "D"),
        ]
        gr = fit_affine(gcps)
        # Round-trip: take a pixel point, forward to (lat, lon), then inverse.
        x0, y0 = 300, 200
        lat, lon = gr.forward(x0, y0)
        x1, y1 = gr.inverse(lat, lon)
        assert abs(x0 - x1) < 1e-3
        assert abs(y0 - y1) < 1e-3

    def test_drops_one_outlier_when_six_anchors_supplied(self):
        gcps = [_gcp(x, y, name) for x, y, name in [
            (100,  50, "A"), (400,  60, "B"), (200, 200, "C"),
            (450, 250, "D"), (350, 400, "E"), (150, 380, "F"),
        ]]
        # Inject a wildly off bad anchor — 5 km from where it should be
        bad = GroundControlPoint(
            x_px=300, y_px=150,
            lat=LAT0 + 0.05, lon=LON0 + 0.05,    # ~5 km away
            label="BAD",
        )
        gr = fit_affine(gcps + [bad], drop_outliers=True)
        assert "BAD" in gr.dropped_labels
        # Surviving fit is still excellent
        assert gr.rmse_m < 1.0
        assert gr.n_anchors == 6

    def test_raises_when_too_few_gcps(self):
        gcps = [_gcp(100, 50, "A"), _gcp(200, 80, "B")]
        with pytest.raises(ValueError):
            fit_affine(gcps)

    def test_does_not_drop_when_below_min_after_drop(self):
        # 3 anchors + 1 outlier — dropping would leave only 3, which is the
        # min, so we should still drop. With min=3 the keep mask must be ≥3.
        gcps = [_gcp(100, 50, "A"), _gcp(400, 60, "B"), _gcp(250, 350, "C")]
        bad = GroundControlPoint(
            x_px=300, y_px=200, lat=LAT0 + 1.0, lon=LON0,
            label="WAY_OFF",
        )
        gr = fit_affine(gcps + [bad], drop_outliers=True)
        # With 4 input and min=3, dropping 1 leaves 3 → allowed.
        assert "WAY_OFF" in gr.dropped_labels
        assert gr.n_anchors == 3

    def test_keeps_all_when_no_outliers(self):
        gcps = [_gcp(x, y, n) for x, y, n in [
            (100, 50, "A"), (400, 60, "B"),
            (250, 350, "C"), (450, 250, "D"),
        ]]
        gr = fit_affine(gcps, drop_outliers=True)
        assert gr.dropped_labels == ()
        assert gr.n_anchors == 4


# --- projection ----------------------------------------------------------

class TestProjectPolyline:
    def test_polyline_lengths_consistent_after_projection(self):
        gcps = [_gcp(x, y, n) for x, y, n in [
            (100, 50, "A"), (500, 60, "B"),
            (250, 400, "C"), (450, 450, "D"),
        ]]
        gr = fit_affine(gcps)
        # Two pixel points 100 px apart along the x axis, near the centre.
        coords = project_polyline(gr, [(200, 200), (300, 200)])
        assert len(coords) == 2
        # Distance between projected coords should be ~100 m (since PX_PER_M=1).
        from stravart.crossref import haversine_km
        d_km = haversine_km(*coords[0], *coords[1])
        assert abs(d_km * 1000 - 100) < 1.0

    def test_empty_polyline(self):
        gcps = [_gcp(100, 50, "A"), _gcp(300, 60, "B"), _gcp(200, 300, "C")]
        gr = fit_affine(gcps)
        assert project_polyline(gr, []) == []


# --- bbox helper ---------------------------------------------------------

class TestBboxOfGeocoords:
    def test_pads_isotropically(self):
        coords = [(51.50, -0.10), (51.51, -0.09)]
        s, n, w, e = bbox_of_geocoords(coords, pad_m=200)
        # Tight bbox would be (51.50, 51.51, -0.10, -0.09); pad expands.
        assert s < 51.50
        assert n > 51.51
        assert w < -0.10
        assert e > -0.09

    def test_zero_pad(self):
        coords = [(51.50, -0.10), (51.51, -0.09)]
        s, n, w, e = bbox_of_geocoords(coords, pad_m=0)
        assert s == pytest.approx(51.50)
        assert n == pytest.approx(51.51)

    def test_raises_on_empty(self):
        with pytest.raises(ValueError):
            bbox_of_geocoords([])
