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
from preview import project_outline, scale_for_distance    # noqa: E402
from route_generator import generate, generate_search      # noqa: E402
from shapes import SHAPES, SHAPES_FULL                     # noqa: E402

from models import (                                       # noqa: E402
    GenerateRequest,
    GenerateResponse,
    GeoJSONLineString,
    HealthResponse,
    JobStatus,
    PreviewRequest,
    PreviewResponse,
    ShapeMeta,
    ShapesResponse,
    ShareRequest,
    ShareResponse,
)
from jobs import JobStore                                  # noqa: E402
from store import ShareStore                               # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Per-family display metadata. Alternates inherit the family entry plus a
# numeric suffix; the picker UI groups by family so the user picks an
# animal first, then optionally a variant.
FAMILY_METADATA: Dict[str, Dict[str, str]] = {
    "pig":     {"name": "Pig",     "emoji": "🐷", "distinctive_features": "floppy round ear, side-profile silhouette"},
    "cat":     {"name": "Cat",     "emoji": "🐱", "distinctive_features": "pointy ears, tail curling up over back"},
    "dog":     {"name": "Dog",     "emoji": "🐶", "distinctive_features": "floppy ear, long snout, longer body"},
    "dino":    {"name": "Dino",    "emoji": "🦖", "distinctive_features": "long neck, three back plates"},
    "chicken": {"name": "Chicken", "emoji": "🐔", "distinctive_features": "jagged comb, beak, layered tail feathers"},
}


def _shape_meta_for(shape_id: str) -> Dict[str, str]:
    """Best-effort lookup: family metadata first, then per-shape METADATA
    description. Falls back to a generic entry so the API never 500s on
    a newly-added shape that isn't in FAMILY_METADATA yet."""
    s = SHAPES_FULL.get(shape_id)
    family = s.family if s else shape_id.split("_")[0]
    fam_meta = FAMILY_METADATA.get(family, {
        "name": family.capitalize(),
        "emoji": "🏃",
        "distinctive_features": (s.metadata.get("description", "") if s else ""),
    })
    return {**fam_meta, "family": family}


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
job_store = JobStore(max_workers=4)


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


def _build_shape_meta(shape_id: str) -> ShapeMeta:
    s = SHAPES_FULL.get(shape_id)
    fam_meta = _shape_meta_for(shape_id)
    is_default = (shape_id == fam_meta["family"])
    description = (s.metadata.get("description", "") if s else "")
    # Alternates get a "Pig (alt 3)" style label so the picker can render
    # them under the same family heading without colliding.
    label = fam_meta["name"]
    if not is_default and "_candidate_" in shape_id:
        n = shape_id.rsplit("_", 1)[-1]
        label = f"{fam_meta['name']} (alt {n})"
    return ShapeMeta(
        id=shape_id,
        name=label,
        emoji=fam_meta["emoji"],
        distinctive_features=fam_meta["distinctive_features"],
        family=fam_meta["family"],
        is_default=is_default,
        description=description,
    )


@app.get("/shapes", response_model=ShapesResponse)
def list_shapes() -> ShapesResponse:
    """List every registered shape. Defaults come first per family,
    alternates after, ordered by family name."""
    family_order = list(FAMILY_METADATA.keys())

    def sort_key(sid: str):
        s = SHAPES_FULL.get(sid)
        family = s.family if s else sid
        # Defaults sort first within family (by putting "" before any
        # candidate suffix).
        suffix = "" if sid == family else sid[len(family):]
        try:
            fi = family_order.index(family)
        except ValueError:
            fi = len(family_order)
        return (fi, family, suffix)

    return ShapesResponse(
        shapes=[_build_shape_meta(sid) for sid in sorted(SHAPES.keys(), key=sort_key)]
    )


def _run_generate(req: GenerateRequest) -> GenerateResponse:
    """Pure compute path — no FastAPI / no HTTPException — so this same body
    runs both as a synchronous /generate and inside the /jobs background
    worker.

    Routing-mode policy:

    * `search_radius_km` set → multi-center fidelity search (Section 6
      of the plan). Slower (15+ OSRM calls) but tries hard to find a
      street grid that fits the shape.

    * Otherwise (`search_radius_km` is None) → tight 1-center search
      around the user's chosen point with 5 narrow scales. This used to
      route the legacy iterative scaler, which was prone to overshooting
      distance and to picking a bad scale on hostile street grids.
      Switching to a tiny grid-search:
        - applies the 2× distance hard cap,
        - blends Hausdorff + Fréchet + IoU instead of relying on
          Hausdorff alone,
      and costs at most ~5 OSRM calls (≈ 6 s on the public demo) — fast
      enough that mobile fetch() doesn't time out.
    """
    if req.shape not in SHAPES:
        raise HTTPException(404, f"Unknown shape '{req.shape}'. "
                                  f"See GET /shapes for available shapes.")

    target_m = req.distance_km * 1000.0
    if req.search_radius_km is not None:
        result = generate_search(
            outline=SHAPES[req.shape],
            center_lat=req.lat,
            center_lon=req.lon,
            target_distance_m=target_m,
            search_radius_km=req.search_radius_km,
            n_candidates=req.candidates,
            n_scales=req.scales,
            n_waypoints=req.waypoints,
            verify=VERIFY,
        )
    else:
        # Tight single-center search: 1 candidate (the user's point),
        # 5 scales spanning 0.7..1.3× of target. Distance cap still on.
        result = generate_search(
            outline=SHAPES[req.shape],
            center_lat=req.lat,
            center_lon=req.lon,
            target_distance_m=target_m,
            search_radius_km=0.001,   # forces single-center; no ring
            n_candidates=1,
            n_scales=5,
            n_waypoints=req.waypoints,
            verify=VERIFY,
        )

    geojson_coords = [(lon, lat) for lat, lon in result.polyline]
    name = f"{_shape_meta_for(req.shape)['name']} Run"
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
        fidelity=result.fidelity,
        chosen_lat=result.center_lat,
        chosen_lon=result.center_lon,
    )


@app.post("/generate", response_model=GenerateResponse)
def generate_route(req: GenerateRequest) -> GenerateResponse:
    """Synchronous route generation. Suitable for fast (basic) requests but
    NOT for the multi-center search — mobile browsers kill long fetches when
    the user backgrounds the tab. For search mode, use POST /jobs and poll
    GET /jobs/{id}."""
    try:
        return _run_generate(req)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Route generation failed: {e}") from e


@app.post("/jobs", response_model=JobStatus)
def start_generate_job(req: GenerateRequest) -> JobStatus:
    """Kick off a route-generation job in the background. Returns immediately
    with a job id the client polls via GET /jobs/{id}.

    Designed for mobile: iOS Safari kills long fetch() calls when the tab is
    backgrounded, so the multi-OSRM search has to run server-side and be
    polled — short polls survive backgrounding fine."""
    # Validate up-front so 404s come back immediately, not via a job error.
    if req.shape not in SHAPES:
        raise HTTPException(404, f"Unknown shape '{req.shape}'. "
                                 f"See GET /shapes for available shapes.")

    def work(job):
        return _run_generate(req).model_dump()

    job = job_store.submit(work)
    return JobStatus(
        id=job.id,
        status=job.status,
        progress=job.progress,
        progress_msg=job.progress_msg,
        error=job.error,
        result=None,
    )


@app.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    """Poll a route-generation job. Returns status (`pending`, `running`,
    `done`, `error`) plus the full GenerateResponse once status == "done"."""
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found or expired")
    return JobStatus(
        id=job.id,
        status=job.status,
        progress=job.progress,
        progress_msg=job.progress_msg,
        error=job.error,
        result=GenerateResponse(**job.result) if job.result else None,
    )


# ---- Preview (no OSRM) -----------------------------------------------------

@app.post("/preview", response_model=PreviewResponse)
def preview_shape(req: PreviewRequest) -> PreviewResponse:
    """Project the idealized outline at the given center+distance and return
    the waypoints WITHOUT calling OSRM. Lets the web/iOS clients render a
    doodle preview before the user commits to a (rate-limited) /generate."""
    if req.shape not in SHAPES:
        raise HTTPException(404, f"Unknown shape '{req.shape}'. "
                                 f"See GET /shapes for available shapes.")
    outline = SHAPES[req.shape]
    target_m = req.distance_km * 1000.0
    scale = scale_for_distance(outline, target_m)
    waypoints = project_outline(outline, req.lat, req.lon, scale)
    geojson_coords = [(lon, lat) for lat, lon in waypoints]
    return PreviewResponse(
        shape=req.shape,
        scale_m_per_unit=scale,
        center_lat=req.lat,
        center_lon=req.lon,
        waypoints=waypoints,
        geojson=GeoJSONLineString(coordinates=geojson_coords),
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
    name = f"{_shape_meta_for(payload['shape'])['name']} Run"
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
    name = f"{_shape_meta_for(payload['shape'])['name']} Run"
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
