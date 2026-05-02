"""End-to-end API tests using FastAPI's TestClient.

OSRM is patched out so the suite runs offline. The tests exercise the
HTTP contract — status codes, JSON shape, GeoJSON LineString [lon,lat]
ordering, GPX presence — rather than the routing math (which is covered
by the prototype-level tests).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from osrm_client import RouteResult


@pytest.fixture
def client():
    return TestClient(app)


def _fake_route_through(distance_m: float = 10500.0):
    """Return a stand-in for osrm_client.route_through that yields a fixed
    polyline and distance — enough to exercise the endpoint plumbing."""
    def fake(waypoints, profile="foot", base_url="", verify=True):
        return RouteResult(
            coordinates=list(waypoints),
            distance_m=distance_m,
            duration_s=distance_m,
        )
    return fake


class TestHealth:
    def test_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["shapes_loaded"] == 5


class TestShapes:
    def test_lists_all_five(self, client):
        r = client.get("/shapes")
        assert r.status_code == 200
        ids = [s["id"] for s in r.json()["shapes"]]
        assert sorted(ids) == ["cat", "chicken", "dino", "dog", "pig"]

    def test_each_shape_has_metadata(self, client):
        for shape in client.get("/shapes").json()["shapes"]:
            assert shape["name"]
            assert shape["emoji"]
            assert shape["distinctive_features"]


class TestGenerate:
    def test_happy_path(self, client):
        with patch("route_generator.route_through",
                   side_effect=_fake_route_through(10500.0)):
            r = client.post("/generate", json={
                "shape": "pig",
                "lat": 51.75,
                "lon": -0.34,
                "distance_km": 10.0,
            })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["shape"] == "pig"
        assert body["target_distance_m"] == 10000.0
        assert body["routed_distance_m"] == 10500.0
        assert body["error_pct"] == pytest.approx(5.0)
        assert body["geojson"]["type"] == "LineString"
        assert len(body["geojson"]["coordinates"]) >= 2
        # GeoJSON is [lon, lat] — the first coord's longitude should be
        # negative-ish (UK) and latitude ~51.
        lon, lat = body["geojson"]["coordinates"][0]
        assert -1.0 < lon < 1.0
        assert 51.0 < lat < 52.0
        assert body["gpx"].startswith("<?xml")
        assert "<gpx" in body["gpx"]
        assert "<rte>" in body["gpx"]

    def test_unknown_shape_returns_404(self, client):
        r = client.post("/generate", json={
            "shape": "unicorn",
            "lat": 51.75, "lon": -0.34, "distance_km": 10.0,
        })
        assert r.status_code == 404
        assert "unicorn" in r.json()["detail"]

    def test_invalid_lat_rejected(self, client):
        r = client.post("/generate", json={
            "shape": "pig", "lat": 999.0, "lon": -0.34, "distance_km": 10.0,
        })
        assert r.status_code == 422   # Pydantic validation

    def test_zero_distance_rejected(self, client):
        r = client.post("/generate", json={
            "shape": "pig", "lat": 51.75, "lon": -0.34, "distance_km": 0,
        })
        assert r.status_code == 422

    def test_osrm_failure_becomes_502(self, client):
        with patch("route_generator.route_through",
                   side_effect=RuntimeError("OSRM NoRoute")):
            r = client.post("/generate", json={
                "shape": "cat", "lat": 51.5, "lon": -0.16, "distance_km": 10.0,
            })
        assert r.status_code == 502
        assert "Route generation failed" in r.json()["detail"]


class TestCors:
    def test_options_preflight_succeeds(self, client):
        r = client.options(
            "/generate",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        # Starlette returns 200 for handled CORS preflight.
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "*"
