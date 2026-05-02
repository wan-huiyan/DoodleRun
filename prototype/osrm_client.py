"""Thin wrapper around the public OSRM demo server (router.project-osrm.org).

The demo server is rate-limited and intended for light testing; we batch all
waypoints into a single /route request and add a short delay between calls.
For production use, swap BASE_URL for a self-hosted OSRM Docker container with
a foot profile built from a local Geofabrik extract.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

import requests

BASE_URL = "https://router.project-osrm.org"
DEFAULT_PROFILE = "foot"
REQUEST_DELAY_S = 1.1


def macos_keychain_bundle(cache_path: Optional[str] = None) -> str:
    """Export macOS keychain trust roots to a PEM file and return its path.

    On corporate networks that perform SSL inspection (Netskope, Zscaler,
    Palo Alto, etc.), the inspection root CA lives in the macOS keychain but
    not in the certifi bundle that requests uses by default. Calling this
    once per process lets requests verify the inspected certificate chain.
    """
    if sys.platform != "darwin":
        raise RuntimeError("macos_keychain_bundle is only meaningful on macOS")
    if cache_path is None:
        cache_path = os.path.join(tempfile.gettempdir(), "doodlerun-ca.pem")
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return cache_path

    keychains = [
        "/Library/Keychains/System.keychain",
        "/System/Library/Keychains/SystemRootCertificates.keychain",
        os.path.expanduser("~/Library/Keychains/login.keychain-db"),
    ]
    with open(cache_path, "wb") as out:
        for kc in keychains:
            if not os.path.exists(kc):
                continue
            res = subprocess.run(
                ["security", "find-certificate", "-a", "-p", kc],
                capture_output=True, check=False,
            )
            if res.returncode == 0 and res.stdout:
                out.write(res.stdout)
    if os.path.getsize(cache_path) == 0:
        raise RuntimeError("Failed to export any certificates from the keychain")
    return cache_path


@dataclass
class RouteResult:
    coordinates: List[Tuple[float, float]]   # ordered (lat, lon) along the road
    distance_m: float
    duration_s: float


def route_through(
    waypoints: List[Tuple[float, float]],
    profile: str = DEFAULT_PROFILE,
    base_url: str = BASE_URL,
    verify: Union[bool, str] = True,
) -> RouteResult:
    """Route a single trip that visits every waypoint in order.

    Args:
        waypoints: ordered list of (lat, lon) the route must pass through.
        profile: OSRM routing profile. The demo server's "foot" profile prefers
            sidewalks and footpaths; "walking" is an alias on some deployments.
        verify: passed straight through to requests; either a CA bundle path,
            True for the certifi default, or False to skip verification.

    Returns:
        RouteResult with the snapped polyline (lat, lon) and total distance.
    """
    if len(waypoints) < 2:
        raise ValueError("Need at least 2 waypoints")

    # OSRM expects lon,lat (not lat,lon) and semicolon-separated.
    coord_str = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)
    url = f"{base_url}/route/v1/{profile}/{coord_str}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
        "annotations": "false",
    }

    time.sleep(REQUEST_DELAY_S)
    resp = requests.get(url, params=params, timeout=60, verify=verify)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(f"OSRM returned no route: {data.get('code')} {data.get('message', '')}")

    route = data["routes"][0]
    geometry = route["geometry"]["coordinates"]   # list of [lon, lat]
    coords = [(lat, lon) for lon, lat in geometry]
    return RouteResult(
        coordinates=coords,
        distance_m=float(route["distance"]),
        duration_s=float(route["duration"]),
    )
