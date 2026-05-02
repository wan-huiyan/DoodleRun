# DoodleRun

Plan running routes that draw animal shapes on the map. Set a target distance,
the app generates a route that traces an animal outline snapped to real
streets/trails, and you export it as GPX for Garmin/Strava.

**Available shapes:** 🐷 pig · 🐱 cat · 🐶 dog · 🦖 dino · 🐔 chicken

## Layout

```
DoodleRun/
├── prototype/      # Phase 1: Python prototype (build & verify here first)
│   ├── *_shape.py  # one outline per animal
│   ├── shapes.py   # registry that the --shape CLI flag reads
│   └── tests/      # pytest suite (offline pieces + recorded OSRM fixture)
├── samples/        # committed reference renders for each shape
├── ios-app/        # Phase 2: SwiftUI + MapKit iPhone app (TBD)
└── output/         # Generated GPX/HTML — gitignored, regenerable
```

## Phase 1 — Python prototype

```
cd prototype
pip install -r requirements.txt
python main.py --shape pig --lat 37.7530 --lon -122.4830 --distance 10.0
```

`--shape` accepts `pig`, `cat`, `dog`, `dino`, or `chicken`. Outputs land in
`../output/<shape>_route.gpx` (Garmin/Strava import) and
`../output/<shape>_route.html` (interactive Folium preview with the snapped
route in blue overlaid on the idealized outline in red dashed).

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

- **Grid neighborhoods (Sunset, Richmond, Manhattan):** converges within
  ±15% for ~10 km targets across all five shapes.
- **Dense/hilly downtown (SOMA, Civic Center):** features get warped into
  multi-block loops; bump the target to ~15 km+ for the shape to stay
  recognizable.
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

36 tests cover the offline pieces (resample, projection, GPX writer, all five
shape definitions). OSRM is exercised against a recorded fixture
(`tests/fixtures/osrm_route.json`) so the suite never touches the network.

## Sample outputs

`samples/` contains a 10 km reference render of every shape, generated around
the SF Sunset District grid. Open the HTML files in a browser to see the
snapped route overlaid on the idealized outline:

| Shape | Routed | File |
|---|---|---|
| pig 🐷 | 11.44 km | [samples/pig_route.html](samples/pig_route.html) |
| cat 🐱 | 11.03 km | [samples/cat_route.html](samples/cat_route.html) |
| dog 🐶 | 10.72 km | [samples/dog_route.html](samples/dog_route.html) |
| dino 🦖 | 11.59 km | [samples/dino_route.html](samples/dino_route.html) |
| chicken 🐔 | 10.60 km | [samples/chicken_route.html](samples/chicken_route.html) |

## Phase 2 — iOS app (TBD)

SwiftUI + MapKit. Pick start point, target distance, shape; preview on map;
export GPX via share sheet. Will likely call a small FastAPI service that
proxies a self-hosted OSRM container.
