"""DoodleRun FastAPI service.

Wraps the Phase 1 prototype's route generator behind a small HTTP API the
iOS app calls. Imports the pipeline modules from `../prototype/` via
sys.path so we don't have to repackage them — the prototype is the source
of truth for shape definitions and routing logic.
"""

from __future__ import annotations

import os
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

PROTOTYPE_DIR = (Path(__file__).resolve().parent.parent / "prototype")
sys.path.insert(0, str(PROTOTYPE_DIR))

# Imports from the prototype package (after sys.path injection).
from gpx_export import gpx_to_string                       # noqa: E402
from kml_export import kml_to_string                       # noqa: E402
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
    ShareRequest,
    ShareResponse,
)
from store import ShareStore                               # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

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


def _local_ip() -> str:
    """Best-effort LAN IP for printing a phone-friendly URL on startup.

    Connects a UDP socket to a public address — no packets are actually sent,
    but this forces the OS to pick the routable interface and we read its
    bound address. Falls back to localhost if there's no network.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Best-guess port: uvicorn's default is 8000; if you launched with a
    # different --port, the displayed URL lies — but the line right above
    # uvicorn's own log makes the actual port obvious. Worth it for the
    # convenience of having the LAN URL printed at startup.
    ip = _local_ip()
    port = os.environ.get("UVICORN_PORT", "8000")
    banner = (
        "\n"
        "  ┌─────────────────────────────────────────────────┐\n"
        f"  │ 🏃 DoodleRun ready                              │\n"
        f"  │ open on your phone: http://{ip}:{port}".ljust(53) + "│\n"
        f"  │ on this computer:   http://localhost:{port}".ljust(53) + "│\n"
        "  └─────────────────────────────────────────────────┘\n"
    )
    print(banner, flush=True)
    yield


app = FastAPI(
    title="DoodleRun",
    description="Generate animal-shaped running routes snapped to streets.",
    version="0.1.0",
    lifespan=lifespan,
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

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

share_store = ShareStore()


@app.get("/", response_class=HTMLResponse)
def root() -> HTMLResponse:
    """Serve the Leaflet SPA. Users open `http://<server>:8000/` on their
    phone to get a polished mobile interface for picking a shape, distance,
    and start point — no Xcode required."""
    template = STATIC_DIR / "app.html"
    if not template.exists():
        raise HTTPException(500, "app.html missing")
    return HTMLResponse(template.read_text(encoding="utf-8"))


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

    # Render GPX + KML into strings so the client can offer share-sheet
    # exports without a second roundtrip. KML is the format Google My Maps
    # imports natively.
    name = f"{SHAPE_METADATA[req.shape]['name']} Run"
    desc = f"GPS-art {req.shape}, ~{result.distance_m / 1000:.2f} km"
    gpx_text = gpx_to_string(result.polyline, name=name, description=desc)
    kml_text = kml_to_string(result.polyline, name=name, description=desc)

    return GenerateResponse(
        shape=req.shape,
        target_distance_m=target_m,
        routed_distance_m=result.distance_m,
        error_pct=(result.distance_m - target_m) / target_m * 100.0,
        geojson=GeoJSONLineString(coordinates=geojson_coords),
        waypoints=result.waypoints,
        gpx=gpx_text,
        kml=kml_text,
    )


# ---- Share / web viewer ----------------------------------------------------

@app.post("/share", response_model=ShareResponse)
def create_share(req: ShareRequest) -> ShareResponse:
    """Stash the route in memory and hand back a URL the user can open in
    any mobile browser to view the route on a Leaflet map. The URL has no
    server prefix in the response — clients should prepend the API base URL
    they already know."""
    payload = {
        "shape": req.shape,
        "geojson": req.geojson.model_dump(),
        "waypoints": req.waypoints,
        "routed_distance_m": req.routed_distance_m,
    }
    share_id = share_store.put(payload)
    return ShareResponse(
        id=share_id,
        viewer_url=f"/v/{share_id}",
        json_url=f"/shared/{share_id}",
        expires_in_seconds=share_store.ttl_seconds(),
    )


def _polyline_from_share(payload: dict) -> list[tuple[float, float]]:
    """Reconstruct (lat, lon) tuples from a share payload's GeoJSON LineString."""
    coords = payload["geojson"]["coordinates"]
    return [(lat, lon) for lon, lat in coords]


# Register the dotted-suffix download routes BEFORE the bare /shared/{id} so
# Starlette doesn't match `abc.gpx` against the JSON handler with id="abc.gpx".

@app.get("/shared/{share_id}.gpx")
def download_shared_gpx(share_id: str) -> Response:
    payload = share_store.get(share_id)
    if payload is None:
        raise HTTPException(404, "Share link not found or expired")
    polyline = _polyline_from_share(payload)
    name = f"{SHAPE_METADATA.get(payload['shape'], {}).get('name', payload['shape'])} Run"
    text = gpx_to_string(polyline, name=name,
                         description=f"GPS-art {payload['shape']}")
    return Response(
        content=text,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{payload["shape"]}_route.gpx"'},
    )


@app.get("/shared/{share_id}.kml")
def download_shared_kml(share_id: str) -> Response:
    payload = share_store.get(share_id)
    if payload is None:
        raise HTTPException(404, "Share link not found or expired")
    polyline = _polyline_from_share(payload)
    name = f"{SHAPE_METADATA.get(payload['shape'], {}).get('name', payload['shape'])} Run"
    text = kml_to_string(polyline, name=name,
                         description=f"GPS-art {payload['shape']}")
    return Response(
        content=text,
        media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": f'attachment; filename="{payload["shape"]}_route.kml"'},
    )


@app.get("/shared/{share_id}")
def get_shared(share_id: str) -> dict:
    """Raw JSON for the viewer's fetch() — separated from the HTML so the
    same payload can power other clients later."""
    payload = share_store.get(share_id)
    if payload is None:
        raise HTTPException(404, "Share link not found or expired")
    return payload


@app.get("/v/{share_id}", response_class=HTMLResponse)
def view_shared(share_id: str) -> HTMLResponse:
    """Render the Leaflet viewer with the share id baked into the page so the
    client-side JS knows which /shared/{id} to fetch."""
    if share_store.get(share_id) is None:
        raise HTTPException(404, "Share link not found or expired")
    template_path = STATIC_DIR / "viewer.html"
    if not template_path.exists():
        raise HTTPException(500, "Viewer template missing")
    html = template_path.read_text(encoding="utf-8")
    # Naive substitution — the template controls its own escape contexts.
    html = html.replace("__SHARE_ID__", share_id)
    return HTMLResponse(html)
