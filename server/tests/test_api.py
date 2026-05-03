"""End-to-end API tests using FastAPI's TestClient.

OSRM is patched out so the suite runs offline. The tests exercise the
HTTP contract — status codes, JSON shape, GeoJSON LineString [lon,lat]
ordering, GPX presence — rather than the routing math (which is covered
by the prototype-level tests).

Jobs run inline (synchronously inside the test thread) via the
`JOBS_INLINE=1` env var — keeps the test deterministic and dodges
worker-thread teardown races between tests.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("JOBS_INLINE", "1")

from fastapi.testclient import TestClient   # noqa: E402

from main import app                        # noqa: E402
from osrm_client import RouteResult         # noqa: E402


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
        # 5 defaults + alternates (currently pig_3, dog_3, dino_2, dino_4).
        # Assert ≥5 rather than ==5 so adding alternates doesn't break tests.
        assert body["shapes_loaded"] >= 5


class TestShapes:
    def test_lists_all_default_animals(self, client):
        r = client.get("/shapes")
        assert r.status_code == 200
        ids = [s["id"] for s in r.json()["shapes"]]
        # Every default family must be present.
        for required in ("cat", "chicken", "dino", "dog", "pig"):
            assert required in ids, f"missing default family {required}"

    def test_each_shape_has_metadata(self, client):
        for shape in client.get("/shapes").json()["shapes"]:
            assert shape["name"]
            assert shape["emoji"]
            assert shape["distinctive_features"]
            assert shape["family"]
            assert "is_default" in shape

    def test_defaults_are_flagged(self, client):
        shapes = client.get("/shapes").json()["shapes"]
        defaults = [s for s in shapes if s["is_default"]]
        # One default per registered family.
        families = {s["family"] for s in shapes}
        assert len(defaults) == len(families)


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
        # KML field present and parseable.
        assert body["kml"].startswith("<?xml")
        assert '<kml xmlns="http://www.opengis.net/kml/2.2">' in body["kml"]
        assert "<LineString>" in body["kml"]

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


class TestJobs:
    """The async /jobs path is what the SPA actually uses (mobile browsers
    kill long fetches). With JOBS_INLINE=1 the work runs synchronously in
    the test thread, so by the time POST /jobs returns the job is already
    in `done` or `error` state."""

    def test_post_jobs_runs_to_completion(self, client):
        with patch("route_generator.route_through",
                   side_effect=_fake_route_through(11000.0)):
            r = client.post("/jobs", json={
                "shape": "pig",
                "lat": 51.75, "lon": -0.34, "distance_km": 10.0,
            })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"]
        # Inline mode: the worker has finished by the time POST returns.
        assert body["status"] == "done"

    def test_get_job_returns_full_result(self, client):
        with patch("route_generator.route_through",
                   side_effect=_fake_route_through(11000.0)):
            job_id = client.post("/jobs", json={
                "shape": "pig", "lat": 51.75, "lon": -0.34, "distance_km": 10.0,
            }).json()["id"]
            r = client.get(f"/jobs/{job_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "done"
        result = body["result"]
        assert result is not None
        assert result["shape"] == "pig"
        assert result["routed_distance_m"] == 11000.0
        assert result["geojson"]["type"] == "LineString"
        assert result["gpx"].startswith("<?xml")
        assert result["kml"].startswith("<?xml")

    def test_post_jobs_unknown_shape_returns_404_immediately(self, client):
        r = client.post("/jobs", json={
            "shape": "unicorn", "lat": 51.75, "lon": -0.34, "distance_km": 10.0,
        })
        # Validation is up-front so the SPA can show a friendly error
        # without polling — only real OSRM/network errors surface as
        # job.status == "error".
        assert r.status_code == 404

    def test_get_unknown_job_returns_404(self, client):
        r = client.get("/jobs/does-not-exist")
        assert r.status_code == 404

    def test_job_error_propagates(self, client):
        # When every OSRM call fails, generate_search() raises a single
        # "every candidate failed" RuntimeError. The job's `error` field
        # surfaces that to the SPA as a polled status payload, so the
        # spinner can stop and the message can be shown.
        with patch("route_generator.route_through",
                   side_effect=RuntimeError("OSRM NoRoute")):
            job_id = client.post("/jobs", json={
                "shape": "pig", "lat": 51.75, "lon": -0.34, "distance_km": 10.0,
            }).json()["id"]
            r = client.get(f"/jobs/{job_id}")
        body = r.json()
        assert body["status"] == "error"
        assert body["result"] is None
        assert "candidate" in body["error"].lower()


class TestPreviewEndpoint:
    """The /preview endpoint must return projected waypoints WITHOUT calling
    OSRM — that's the whole point: shape-design iteration without burning
    rate-limited routing requests."""

    def test_returns_waypoints_without_osrm(self, client):
        # If preview accidentally hit OSRM this patch would break it; the
        # request must succeed without ever entering route_through.
        with patch("route_generator.route_through",
                   side_effect=AssertionError("preview must not call OSRM")):
            r = client.post("/preview", json={
                "shape": "pig", "lat": 51.75, "lon": -0.34, "distance_km": 10.0,
            })
        assert r.status_code == 200
        body = r.json()
        assert body["shape"] == "pig"
        assert body["scale_m_per_unit"] > 0
        assert len(body["waypoints"]) >= 10
        # Bbox center should be the requested lat/lon.
        lats = [p[0] for p in body["waypoints"]]
        lons = [p[1] for p in body["waypoints"]]
        assert abs(((min(lats) + max(lats)) / 2) - 51.75) < 1e-4
        assert abs(((min(lons) + max(lons)) / 2) - -0.34) < 1e-4
        # GeoJSON coords must be [lon, lat] pairs.
        gj_coords = body["geojson"]["coordinates"]
        assert len(gj_coords) == len(body["waypoints"])
        assert gj_coords[0][1] == body["waypoints"][0][0]   # geojson lat == waypoint lat

    def test_unknown_shape_404(self, client):
        r = client.post("/preview", json={
            "shape": "unicorn", "lat": 0, "lon": 0, "distance_km": 10.0,
        })
        assert r.status_code == 404


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
