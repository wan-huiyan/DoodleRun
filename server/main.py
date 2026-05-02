"""DoodleRun FastAPI service.

Wraps the Phase 1 prototype's route generator behind a small HTTP API the
iOS app calls. Imports the pipeline modules from `../prototype/` via
sys.path so we don't have to repackage them — the prototype is the source
of truth for shape definitions and routing logic.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

PROTOTYPE_DIR = (Path(__file__).resolve().parent.parent / "prototype")
sys.path.insert(0, str(PROTOTYPE_DIR))

# Imports from the prototype package (after sys.path injection).
from gpx_export import gpx_to_string                       # noqa: E402
from osrm_client import macos_keychain_bundle              # noqa: E402
from route_generator import generate                       # noqa: E402
from shapes import SHAPES                                  # noqa: E402

from models import (                                       # noqa: E402
    GenerateRequest,
    GenerateResponse,
    GeoJSONLineString,
    HealthResponse,
    ShapeMeta,
    ShapesResponse,
)

SHAPE_METADATA: Dict[str, Dict[str, str]] = {
    "pig":     {"name": "Pig",     "emoji": "🐷", "distinctive_features": "curly tail, ear bump, two wide legs"},
    "cat":     {"name": "Cat",     "emoji": "🐱", "distinctive_features": "twin pointed ears, tail curling up over back"},
    "dog":     {"name": "Dog",     "emoji": "🐶", "distinctive_features": "floppy ear, long snout, longer body"},
    "dino":    {"name": "Dino",    "emoji": "🦖", "distinctive_features": "three back spikes, long tapering tail"},
    "chicken": {"name": "Chicken", "emoji": "🐔", "distinctive_features": "three-peak comb, beak, layered tail feathers"},
}


def _resolve_verify() -> object:
    """Resolve the SSL verify argument once at import time.

    The DOODLERUN_CA_BUNDLE env var matches the prototype CLI's --ca-bundle
    flag: set it to "keychain" on macOS behind corporate TLS inspection,
    or to a path for a custom bundle. Default is certifi.
    """
    val = os.environ.get("DOODLERUN_CA_BUNDLE")
    if val == "keychain":
        return macos_keychain_bundle()
    if val:
        return val
    return True


VERIFY = _resolve_verify()

app = FastAPI(
    title="DoodleRun",
    description="Generate animal-shaped running routes snapped to streets.",
    version="0.1.0",
)

# Allow the iOS simulator and any localhost-served preview to call us
# during development. Tighten for production deployments.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", shapes_loaded=len(SHAPES))


@app.get("/shapes", response_model=ShapesResponse)
def list_shapes() -> ShapesResponse:
    return ShapesResponse(
        shapes=[
            ShapeMeta(id=sid, **SHAPE_METADATA[sid])
            for sid in sorted(SHAPES.keys())
        ]
    )


@app.post("/generate", response_model=GenerateResponse)
def generate_route(req: GenerateRequest) -> GenerateResponse:
    if req.shape not in SHAPES:
        raise HTTPException(404, f"Unknown shape '{req.shape}'. "
                                  f"See GET /shapes for available shapes.")

    target_m = req.distance_km * 1000.0
    try:
        result = generate(
            outline=SHAPES[req.shape],
            center_lat=req.lat,
            center_lon=req.lon,
            target_distance_m=target_m,
            n_waypoints=req.waypoints,
            max_iterations=req.iterations,
            verify=VERIFY,
        )
    except Exception as e:
        # OSRM NoRoute / network errors / etc. The CLI keeps the best
        # earlier iteration via try/except inside generate(); only a total
        # first-iteration failure escapes to here.
        raise HTTPException(502, f"Route generation failed: {e}") from e

    # GeoJSON LineString takes [lon, lat]; the polyline holds (lat, lon).
    geojson_coords = [(lon, lat) for lat, lon in result.polyline]

    # Render the GPX into a string so the client can offer it via a share
    # sheet without a second roundtrip.
    gpx_text = gpx_to_string(
        result.polyline,
        name=f"{SHAPE_METADATA[req.shape]['name']} Run",
        description=f"GPS-art {req.shape}, ~{result.distance_m / 1000:.2f} km",
    )

    return GenerateResponse(
        shape=req.shape,
        target_distance_m=target_m,
        routed_distance_m=result.distance_m,
        error_pct=(result.distance_m - target_m) / target_m * 100.0,
        geojson=GeoJSONLineString(coordinates=geojson_coords),
        waypoints=result.waypoints,
        gpx=gpx_text,
    )
