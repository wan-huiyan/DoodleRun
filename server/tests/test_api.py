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
from route_generator import GeneratedRoute


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


def _fake_v2_multi(
    *,
    distance_m: float = 19500.0,
    score: float = 0.27,
    variant_index: int = 1,
):
    """Return a canned `generate_search_v2_multi` that skips OSMnx + Optuna.

    Mirrors the shape of the real return value (a `GeneratedRoute` with the
    Phase-3 extras populated) so the endpoint contract test exercises the
    same fields the production path emits.
    """
    polyline = [(51.75 + 0.001 * i, -0.34 + 0.001 * i) for i in range(20)]
    waypoints = polyline[::2]
    breakdown = {
        "hausdorff": 0.011,
        "frechet": 0.085,
        "area_iou": 0.50,
        "turning": 0.40,
        "weights": {"hausdorff": 0.35, "frechet": 0.30,
                    "area_iou": 0.20, "turning": 0.15},
    }
    best_params = {
        "offset_lat": 0.012, "offset_lon": -0.019,
        "scale_factor": 0.7, "rotation_deg": 161.9,
        "variant_index": variant_index,
    }

    def fake(
        outline_variants,
        center_lat,
        center_lon,
        target_distance_m,
        **_kwargs,
    ):
        return GeneratedRoute(
            waypoints=waypoints,
            polyline=polyline,
            distance_m=distance_m,
            scale_m_per_unit=120.0,
            center_lat=center_lat + 0.012,
            center_lon=center_lon - 0.019,
            fidelity=score,
            rotation_deg=161.9,
            best_params=best_params,
            fidelity_breakdown=breakdown,
        )
    return fake


class TestRoot:
    def test_serves_spa(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        body = r.text
        # Sanity-check the SPA's distinctive markers.
        assert "<title>DoodleRun</title>" in body
        assert 'id="map"' in body
        assert 'id="shapes"' in body  # shape picker container
        assert "leaflet" in body.lower()


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


class TestGenerateLegacy:
    """Legacy (Phase-1 OSRM) generator path — kept callable behind
    `algorithm: "legacy"` for transition / fallback. v2_multi is the new
    default (covered by TestGenerateV2Multi)."""

    def test_happy_path(self, client):
        with patch("route_generator.route_through",
                   side_effect=_fake_route_through(10500.0)):
            r = client.post("/generate", json={
                "shape": "pig",
                "lat": 51.75,
                "lon": -0.34,
                "distance_km": 10.0,
                "algorithm": "legacy",
            })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["shape"] == "pig"
        assert body["algorithm"] == "legacy"
        assert body["target_distance_m"] == 10000.0
        assert body["routed_distance_m"] == 10500.0
        assert body["distance_m"] == 10500.0
        assert body["error_pct"] == pytest.approx(5.0)
        # `score` aliases `fidelity` for the legacy path.
        assert body["score"] == body["fidelity"]
        assert body["score_breakdown"] is None
        assert body["variant_index"] is None
        assert body["geojson"]["type"] == "LineString"
        assert len(body["geojson"]["coordinates"]) >= 2
        # GeoJSON is [lon, lat] — the first coord's longitude should be
        # negative-ish (UK) and latitude ~51.
        lon, lat = body["geojson"]["coordinates"][0]
        assert -1.0 < lon < 1.0
        assert 51.0 < lat < 52.0
        # `polyline` is the same data in [lat, lon] order.
        assert len(body["polyline"]) == len(body["geojson"]["coordinates"])
        assert body["polyline"][0][0] == pytest.approx(lat)
        assert body["polyline"][0][1] == pytest.approx(lon)
        assert body["gpx"].startswith("<?xml")
        assert "<gpx" in body["gpx"]
        assert "<rte>" in body["gpx"]
        # KML field present and parseable.
        assert body["kml"].startswith("<?xml")
        assert '<kml xmlns="http://www.opengis.net/kml/2.2">' in body["kml"]
        assert "<LineString>" in body["kml"]

    def test_unknown_shape_returns_404(self, client):
        r = client.post("/generate", json={
            "shape": "unicorn",
            "lat": 51.75, "lon": -0.34, "distance_km": 10.0,
            "algorithm": "legacy",
        })
        assert r.status_code == 404
        assert "unicorn" in r.json()["detail"]

    def test_invalid_lat_rejected(self, client):
        r = client.post("/generate", json={
            "shape": "pig", "lat": 999.0, "lon": -0.34, "distance_km": 10.0,
            "algorithm": "legacy",
        })
        assert r.status_code == 422   # Pydantic validation

    def test_zero_distance_rejected(self, client):
        r = client.post("/generate", json={
            "shape": "pig", "lat": 51.75, "lon": -0.34, "distance_km": 0,
            "algorithm": "legacy",
        })
        assert r.status_code == 422

    def test_osrm_failure_becomes_502(self, client):
        with patch("route_generator.route_through",
                   side_effect=RuntimeError("OSRM NoRoute")):
            r = client.post("/generate", json={
                "shape": "cat", "lat": 51.5, "lon": -0.16, "distance_km": 10.0,
                "algorithm": "legacy",
            })
        assert r.status_code == 502
        assert "Route generation failed" in r.json()["detail"]


class TestGenerateV2Multi:
    """Phase-3 OSMnx + W-K + Optuna multi-variant path. Patches
    `route_generator.generate_search_v2_multi` so tests stay offline."""

    def test_happy_path_default_algorithm(self, client):
        # Default algorithm is v2_multi — omitting the field should pick it.
        with patch("route_generator.generate_search_v2_multi",
                   side_effect=_fake_v2_multi(distance_m=19500.0,
                                              score=0.273,
                                              variant_index=1)):
            r = client.post("/generate", json={
                "shape": "pig",
                "lat": 51.5074,
                "lon": -0.0148,
                "distance_km": 20.0,
            })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["algorithm"] == "v2_multi"
        assert body["target_distance_m"] == 20000.0
        assert body["routed_distance_m"] == 19500.0
        assert body["distance_m"] == 19500.0
        assert body["score"] == pytest.approx(0.273)
        assert body["fidelity"] == pytest.approx(0.273)  # alias for v2
        assert body["variant_index"] == 1
        assert body["best_params"]["scale_factor"] == pytest.approx(0.7)
        bd = body["score_breakdown"]
        assert bd is not None
        assert bd["hausdorff"] == pytest.approx(0.011)
        assert bd["weights"]["hausdorff"] == pytest.approx(0.35)
        # chosen_lat/lon should reflect the offset applied inside the search.
        assert body["chosen_lat"] == pytest.approx(51.5074 + 0.012)
        assert body["chosen_lon"] == pytest.approx(-0.0148 - 0.019)
        # The polyline + waypoints come from the canned fixture.
        assert len(body["polyline"]) >= 2
        assert len(body["waypoints"]) >= 2

    def test_explicit_algorithm_v2(self, client):
        with patch("route_generator.generate_search_v2_multi",
                   side_effect=_fake_v2_multi()):
            r = client.post("/generate", json={
                "shape": "cat",
                "lat": 37.7559, "lon": -122.4828,
                "distance_km": 18.0,
                "algorithm": "v2_multi",
            })
        assert r.status_code == 200, r.text
        assert r.json()["algorithm"] == "v2_multi"

    def test_distance_below_band_rejected(self, client):
        # 10 km is fine for legacy but below v2_multi's 15 km floor.
        r = client.post("/generate", json={
            "shape": "pig",
            "lat": 51.5074, "lon": -0.0148,
            "distance_km": 10.0,
            "algorithm": "v2_multi",
        })
        assert r.status_code == 422
        assert "v2_multi" in r.json()["detail"]
        assert "15" in r.json()["detail"]

    def test_distance_above_band_rejected(self, client):
        r = client.post("/generate", json={
            "shape": "pig",
            "lat": 51.5074, "lon": -0.0148,
            "distance_km": 35.0,
            "algorithm": "v2_multi",
        })
        # The Pydantic ge=0/le=50 lets 35 through; the v2 endpoint band check
        # rejects it with 422.
        assert r.status_code == 422
        assert "v2_multi" in r.json()["detail"]

    def test_unknown_shape_returns_404(self, client):
        r = client.post("/generate", json={
            "shape": "kraken",
            "lat": 51.5074, "lon": -0.0148, "distance_km": 20.0,
        })
        assert r.status_code == 404

    def test_search_failure_becomes_502(self, client):
        with patch("route_generator.generate_search_v2_multi",
                   side_effect=RuntimeError("Optuna trials all pruned")):
            r = client.post("/generate", json={
                "shape": "dog",
                "lat": 51.5074, "lon": -0.0148, "distance_km": 20.0,
                "algorithm": "v2_multi",
            })
        assert r.status_code == 502
        assert "Route generation failed" in r.json()["detail"]
        assert "Optuna" in r.json()["detail"]

    def test_invalid_algorithm_rejected(self, client):
        r = client.post("/generate", json={
            "shape": "pig",
            "lat": 51.5074, "lon": -0.0148, "distance_km": 20.0,
            "algorithm": "v3_quantum",
        })
        assert r.status_code == 422  # Pydantic Literal validation

    def test_max_variants_propagated(self, client):
        captured = {}

        def fake(outline_variants, center_lat, center_lon, target_distance_m,
                 **kwargs):
            captured["n_variants"] = len(outline_variants)
            captured["n_trials"] = kwargs.get("n_trials")
            captured["timeout_s"] = kwargs.get("timeout_s")
            return _fake_v2_multi()(outline_variants, center_lat, center_lon,
                                    target_distance_m, **kwargs)

        with patch("route_generator.generate_search_v2_multi", side_effect=fake):
            r = client.post("/generate", json={
                "shape": "pig",
                "lat": 51.5074, "lon": -0.0148, "distance_km": 20.0,
                "algorithm": "v2_multi",
                "max_variants": 3,
                "n_trials": 25,
                "timeout_s_per_variant": 45.0,
            })
        assert r.status_code == 200, r.text
        assert captured["n_variants"] <= 3
        assert captured["n_trials"] == 25
        assert captured["timeout_s"] == 45.0


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


@pytest.fixture
def share_payload():
    """A minimal share-request body that round-trips through /share + /shared."""
    return {
        "shape": "pig",
        "geojson": {
            "type": "LineString",
            "coordinates": [
                [-0.34, 51.75], [-0.339, 51.751], [-0.338, 51.752],
                [-0.337, 51.751], [-0.34, 51.75],
            ],
        },
        "waypoints": [[51.75, -0.34], [51.751, -0.339], [51.752, -0.338],
                      [51.751, -0.337], [51.75, -0.34]],
        "routed_distance_m": 10500.0,
    }


class TestShare:
    def test_create_returns_id_and_urls(self, client, share_payload):
        r = client.post("/share", json=share_payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"]
        assert body["viewer_url"] == f"/v/{body['id']}"
        assert body["json_url"] == f"/shared/{body['id']}"
        assert body["expires_in_seconds"] > 0

    def test_get_shared_returns_payload(self, client, share_payload):
        share_id = client.post("/share", json=share_payload).json()["id"]
        r = client.get(f"/shared/{share_id}")
        assert r.status_code == 200
        got = r.json()
        assert got["shape"] == "pig"
        assert got["routed_distance_m"] == 10500.0
        assert got["geojson"]["coordinates"] == share_payload["geojson"]["coordinates"]

    def test_unknown_share_id_404(self, client):
        r = client.get("/shared/does-not-exist")
        assert r.status_code == 404

    def test_viewer_html_substitutes_share_id(self, client, share_payload):
        share_id = client.post("/share", json=share_payload).json()["id"]
        r = client.get(f"/v/{share_id}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        # The page must reference the share id so the JS can fetch /shared/{id}.
        assert share_id in r.text
        # And the placeholder must be gone.
        assert "__SHARE_ID__" not in r.text

    def test_viewer_html_404_for_missing_share(self, client):
        r = client.get("/v/does-not-exist")
        assert r.status_code == 404

    def test_shared_gpx_download(self, client, share_payload):
        share_id = client.post("/share", json=share_payload).json()["id"]
        r = client.get(f"/shared/{share_id}.gpx")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/gpx+xml")
        assert "attachment" in r.headers["content-disposition"]
        assert r.text.startswith("<?xml")
        assert "<rte>" in r.text

    def test_shared_kml_download(self, client, share_payload):
        share_id = client.post("/share", json=share_payload).json()["id"]
        r = client.get(f"/shared/{share_id}.kml")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/vnd.google-earth.kml+xml")
        assert "<LineString>" in r.text
