"""Tests for osrm_client.route_through with a recorded fixture.

We monkey-patch ``requests.get`` so the call returns the recorded response
instead of hitting the public OSRM demo server. The fixture was captured
from a real /route/v1/foot call against router.project-osrm.org with 4
waypoints in the SF Sunset District.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import osrm_client
from osrm_client import REQUEST_DELAY_S, RouteResult, route_through


class FakeResponse:
    def __init__(self, data: dict, status: int = 200):
        self._data = data
        self.status_code = status

    def json(self) -> dict:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_route_through_parses_fixture(osrm_route_response, monkeypatch):
    monkeypatch.setattr(osrm_client.time, "sleep", lambda s: None)
    fake_get = MagicMock(return_value=FakeResponse(osrm_route_response))
    monkeypatch.setattr(osrm_client.requests, "get", fake_get)

    waypoints = [(37.7530, -122.4830), (37.7540, -122.4810),
                 (37.7540, -122.4790), (37.7530, -122.4780)]
    result = route_through(waypoints, verify=False)

    assert isinstance(result, RouteResult)
    assert result.distance_m == pytest.approx(708.9, abs=0.1)
    assert len(result.coordinates) > 0
    # Each coord should be (lat, lon) with realistic SF values.
    for lat, lon in result.coordinates:
        assert 37.7 < lat < 37.8
        assert -122.5 < lon < -122.4
    fake_get.assert_called_once()


def test_route_through_url_encodes_lon_lat_order(osrm_route_response, monkeypatch):
    """OSRM expects lon,lat order — verify we don't accidentally swap."""
    monkeypatch.setattr(osrm_client.time, "sleep", lambda s: None)
    captured = {}
    def capture_get(url, **kwargs):
        captured["url"] = url
        return FakeResponse(osrm_route_response)
    monkeypatch.setattr(osrm_client.requests, "get", capture_get)

    route_through([(37.0, -122.0), (37.1, -122.1)], verify=False)
    # First coord pair in the URL should be "-122.000000,37.000000".
    assert "-122.000000,37.000000" in captured["url"]
    assert "37.000000,-122.000000" not in captured["url"]


def test_route_through_raises_on_zero_route(monkeypatch):
    monkeypatch.setattr(osrm_client.time, "sleep", lambda s: None)
    monkeypatch.setattr(osrm_client.requests, "get",
                        lambda *a, **kw: FakeResponse({"code": "NoRoute", "routes": []}))
    with pytest.raises(RuntimeError, match="OSRM"):
        route_through([(37.0, -122.0), (37.1, -122.1)], verify=False)


def test_route_through_requires_two_waypoints():
    with pytest.raises(ValueError):
        route_through([(37.0, -122.0)])
