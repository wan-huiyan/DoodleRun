"""Shared pytest fixtures and import-path setup.

Adds the prototype directory to sys.path so tests can `import pig_shape`,
`from osrm_client import …`, etc., without an installable package.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

PROTOTYPE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROTOTYPE_DIR))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def osrm_route_response() -> dict:
    """Recorded /route/v1/foot response with 4 waypoints in SF Sunset."""
    with open(FIXTURE_DIR / "osrm_route.json") as f:
        return json.load(f)
