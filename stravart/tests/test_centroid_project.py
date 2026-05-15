"""Tests for the Phase 4b centroid-anchored fallback projection."""

from __future__ import annotations

import math

import pytest

from stravart.centroid_project import (
    CentroidProjection,
    centroid_project_contour,
)


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres between two (lat, lon) points."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * 6_371_000.0 * math.asin(math.sqrt(h))


class TestEmptyAndDegenerate:
    def test_empty_contour_raises(self):
        with pytest.raises(ValueError):
            centroid_project_contour([], city_lat=51.5, city_lon=-0.1)

    def test_single_point_raises(self):
        with pytest.raises(ValueError):
            centroid_project_contour([(10, 10)], city_lat=51.5, city_lon=-0.1)


class TestCentreAtCity:
    def test_bbox_centre_lands_at_city(self):
        # A 200x200 square contour centred on (100, 100) in pixel coords
        # should have its geographic bbox centre at (city_lat, city_lon).
        pix = [(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)]
        out = centroid_project_contour(pix, city_lat=52.50, city_lon=13.40)
        lats = [p[0] for p in out.polyline]
        lons = [p[1] for p in out.polyline]
        centre_lat = (min(lats) + max(lats)) / 2.0
        centre_lon = (min(lons) + max(lons)) / 2.0
        assert abs(centre_lat - 52.50) < 1e-6
        assert abs(centre_lon - 13.40) < 1e-6


class TestScale:
    def test_default_scale_matches_target_width(self):
        # A 1000-pixel-wide contour at the default 4 km target ⇒ ~4 m/px.
        pix = [(0, 100), (1000, 100)]
        out = centroid_project_contour(pix, city_lat=51.5, city_lon=-0.1)
        # bbox_width_m should equal target_width_m (4 km) by construction.
        assert abs(out.bbox_width_m - 4_000.0) < 1.0
        # Endpoint separation in metres ≈ 4 km.
        d = _haversine_m(out.polyline[0], out.polyline[-1])
        assert 3_900.0 < d < 4_100.0

    def test_explicit_scale_overrides_target(self):
        pix = [(0, 0), (100, 0)]
        out = centroid_project_contour(
            pix, city_lat=51.5, city_lon=-0.1,
            scale_m_per_pixel=10.0,
        )
        # 100 px at 10 m/px = 1 km.
        d = _haversine_m(out.polyline[0], out.polyline[-1])
        assert 990.0 < d < 1_010.0


class TestOrientation:
    def test_image_y_growing_downward_maps_to_lat_decreasing(self):
        # In image coords y grows downward; in geographic coords lat grows north.
        # So a pixel below the centre should have lower latitude.
        pix = [(50, 0), (50, 200)]    # same x, py=0 (top) and py=200 (bottom)
        out = centroid_project_contour(pix, city_lat=51.5, city_lon=-0.1)
        top_lat, bot_lat = out.polyline[0][0], out.polyline[1][0]
        assert top_lat > bot_lat   # top of image is more northerly

    def test_pixel_x_increasing_maps_to_lon_increasing(self):
        # Standard image x grows rightward, lon grows eastward.
        pix = [(0, 50), (200, 50)]
        out = centroid_project_contour(pix, city_lat=51.5, city_lon=-0.1)
        west_lon, east_lon = out.polyline[0][1], out.polyline[1][1]
        assert east_lon > west_lon


class TestLatitudeCorrection:
    def test_high_latitude_widens_dlon_per_metre(self):
        # At 60° N, 1 m east is twice as many degrees of longitude as at 0° N
        # (cos(60°)=0.5). Test that a 100 px-wide horizontal line at 60° N
        # spans a wider longitudinal arc than at the equator, for the same scale.
        pix = [(0, 0), (100, 0)]
        eq = centroid_project_contour(
            pix, city_lat=0.0, city_lon=0.0, scale_m_per_pixel=10.0,
        )
        polar = centroid_project_contour(
            pix, city_lat=60.0, city_lon=0.0, scale_m_per_pixel=10.0,
        )
        eq_dlon = abs(eq.polyline[1][1] - eq.polyline[0][1])
        polar_dlon = abs(polar.polyline[1][1] - polar.polyline[0][1])
        # At 60° N the longitude span should be roughly 1/cos(60°) = 2x the
        # equator span for the same metric distance.
        assert 1.9 < polar_dlon / eq_dlon < 2.1
