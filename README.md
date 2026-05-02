# DoodleRun

Plan running routes that draw animal shapes on the map. Set a target distance,
the app generates a route that traces an animal outline snapped to real
streets/trails, and you export it as GPX for Garmin/Strava.

**Available shapes:** 🐷 pig · 🐱 cat · 🐶 dog · 🦖 dino · 🐔 chicken

## Layout

```
DoodleRun/
├── prototype/      # Phase 1: Python prototype (CLI, source of truth for routing)
│   ├── *_shape.py  # one outline per animal
│   ├── shapes.py   # registry that the --shape CLI flag reads
│   ├── gpx_export.py / kml_export.py
│   └── tests/      # pytest suite (offline pieces + recorded OSRM fixture)
├── server/         # Phase 2A: FastAPI service the iOS app calls
│   ├── main.py     # /health, /shapes, /generate, /share, /v/{id}, /shared/{id}{,.gpx,.kml}
│   ├── models.py   # Pydantic request/response schemas
│   ├── store.py    # in-memory share store with TTL
│   ├── static/viewer.html  # mobile-friendly Leaflet viewer
│   ├── Dockerfile  # build context = repo root
│   └── tests/      # endpoint tests with TestClient (OSRM mocked)
├── ios/            # Phase 2B: SwiftUI + MapKit iPhone app
├── samples/        # committed reference renders (HTML + GPX + KML for each shape)
└── output/         # Generated GPX/KML/HTML — gitignored, regenerable
```

## Phase 1 — Python prototype

```
cd prototype
pip install -r requirements.txt
python main.py --shape pig --lat 51.75 --lon -0.34 --distance 10.0
```

`--shape` accepts `pig`, `cat`, `dog`, `dino`, or `chicken`. Outputs land in
`../output/<shape>_route.{gpx,kml,html}`:
- `.gpx` — GPX 1.1 for Garmin Connect / Strava import
- `.kml` — KML 2.2 for Google My Maps / Google Earth import
- `.html` — interactive Folium preview with the snapped route in blue
  overlaid on the idealized outline in red dashed

### Corporate SSL inspection (macOS)

If `requests.exceptions.SSLError: certificate verify failed` shows up, your
network is doing TLS inspection (Netskope, Zscaler, etc.) and the inspection
root CA is in your macOS keychain but not in certifi. Pass `--ca-bundle keychain`
to auto-export the keychain to a temp PEM and use that for verification:

```
python main.py --shape cat --ca-bundle keychain
```

### Picking a center and distance

Street snapping inflates the routed distance well above the shape's geometric
perimeter, especially around the leg "spikes" which force out-and-back
detours. Empirically:

- **Suburban grids (St Albans, Hatfield, US Sunset/Richmond):** converges
  within ±20% for ~10 km targets across all five shapes.
- **Dense central cities (central London, SF SOMA):** features get warped
  into multi-block loops; bump the target to ~15 km+ to stay recognizable.
- **Avoid centers inside large parks (Hyde Park, Regent's Park, Golden
  Gate Park):** OSRM's foot graph treats park interiors as disconnected
  pockets, so a centered shape will project waypoints onto unsnappable
  land and OSRM returns `NoRoute`. Move the center to an adjacent street
  grid; the iteration loop also keeps the best earlier result if a later
  iteration's smaller scale lands waypoints in such a pocket.
- **Realistic minimum:** legs need to span ~2 city blocks each for the
  silhouette to read, which puts the floor around 8 km on a regular grid.

## Pipeline

1. Each animal outline is a list of (x, y) waypoints in `<animal>_shape.py`.
2. `shape_utils.resample` resamples to N evenly-spaced waypoints (default 40).
3. `route_generator.project_shape` centers the bbox on the chosen lat/lon and
   scales it in meters-per-unit so the on-the-ground size makes sense.
4. Single OSRM `/route/v1/foot/` request with all waypoints → snapped polyline.
5. Compare routed distance to target; multiply scale by `√(target/actual)` and
   re-route. Damped iteration (sqrt vs linear) avoids oscillation when many
   segments are fixed-cost detours that don't scale linearly with the shape.
   The best of N iterations is returned.
6. Emit GPX 1.1 (`<rte>/<rtept>` + `<trk>/<trkpt>`) and a Folium HTML preview.

## Tests

```
cd prototype
pip install pytest
python -m pytest tests/ -v
```

45 tests cover the offline pieces (resample, projection, GPX + KML writers,
all five shape definitions, and the iteration loop's resilience to
mid-iteration OSRM failures). OSRM is exercised against a recorded fixture
(`tests/fixtures/osrm_route.json`) so the suite never touches the network.

## Sample outputs

`samples/` contains a 10 km reference render of every shape, generated across
London and Hertfordshire. Open the HTML files in a browser to see the snapped
route overlaid on the idealized outline:

| Shape | Center | Routed | File |
|---|---|---|---|
| pig 🐷 | St Albans, Hertfordshire | 11.54 km | [samples/pig_route.html](samples/pig_route.html) |
| cat 🐱 | Knightsbridge, central London | 14.10 km | [samples/cat_route.html](samples/cat_route.html) |
| dog 🐶 | Hampstead Heath, north London | 12.53 km | [samples/dog_route.html](samples/dog_route.html) |
| dino 🦖 | Hatfield, Hertfordshire | 12.06 km | [samples/dino_route.html](samples/dino_route.html) |
| chicken 🐔 | Clapham Common, south London | 12.21 km | [samples/chicken_route.html](samples/chicken_route.html) |

Central London routes overshoot the 10 km target more than the SF Sunset
grid did (cat 41% over) — Hyde Park, Regent's Park, the river, and railway
crossings all create fixed-cost detours that don't shrink with the shape.
For tighter convergence, prefer suburban grids.

## Phase 2A — FastAPI service

```
cd server
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# behind corp TLS inspection on macOS:
DOODLERUN_CA_BUNDLE=keychain uvicorn main:app --reload --port 8000
```

Endpoints:

| Method | Path | Body / params | Returns |
|---|---|---|---|
| `GET` | `/health` | — | `{status, shapes_loaded}` |
| `GET` | `/shapes` | — | metadata for all 5 shapes (id, name, emoji, distinctive features) |
| `POST` | `/generate` | `{shape, lat, lon, distance_km, waypoints?, iterations?}` | GeoJSON LineString + waypoints + **GPX** 1.1 string + **KML** 2.2 string |
| `POST` | `/share` | `{shape, geojson, waypoints, routed_distance_m}` | `{id, viewer_url, json_url, expires_in_seconds}` — stashes the route in memory and returns a short-lived shareable URL |
| `GET` | `/v/{id}` | — | Mobile-friendly Leaflet HTML viewer with the route loaded |
| `GET` | `/shared/{id}` | — | Raw JSON payload for the viewer to fetch |
| `GET` | `/shared/{id}.gpx` | — | GPX download with `Content-Disposition: attachment` |
| `GET` | `/shared/{id}.kml` | — | KML download (Google My Maps imports it directly) |

The share store is in-memory with a 7-day TTL and a 1024-entry cap; restarts
wipe it. Drop in a Redis or SQLite backend in `server/store.py` if you ever
deploy multiple instances.

Run the test suite: `cd server && python -m pytest tests/ -v` (16 tests,
OSRM mocked, ~1 s).

Container build (context = repo root, server imports prototype/ at runtime):

```
docker build -t doodlerun-server -f server/Dockerfile .
docker run -p 8000:8000 doodlerun-server
```

OpenAPI docs are auto-generated — visit `http://localhost:8000/docs` once
the server is running.

## Phase 2B — iOS app

SwiftUI + MapKit. Pick start point, target distance, shape; preview on map;
export. The export row offers three buttons:

- **GPX** — share sheet with a `.gpx` file (Garmin Connect, Strava, …)
- **KML** — share sheet with a `.kml` file (Google My Maps, Google Earth)
- **Link** — POST to `/share`, get back a `/v/{id}` URL, share it via the
  system share sheet (Messages, AirDrop, copy to clipboard, …)

Calls the FastAPI service at a configurable base URL (default
`http://localhost:8000` for the simulator). See `ios/README.md` for the
Xcode bootstrap instructions.
