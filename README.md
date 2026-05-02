# gps-art-runner

Plan running routes that draw animal shapes on the map. Set a target distance,
the app generates a route that traces an animal outline snapped to real
streets/trails, and you export it as GPX for Garmin/Strava.

**Starting shape: pig.**

## Layout

```
gps-art-runner/
├── prototype/      # Phase 1: Python prototype (build & verify here first)
├── ios-app/        # Phase 2: SwiftUI + MapKit iPhone app (TBD)
└── output/         # Generated GPX files and HTML map previews
```

## Phase 1 — Python prototype

```
cd prototype
pip install -r requirements.txt
python main.py --lat 37.7530 --lon -122.4830 --distance 10.0
```

Outputs:
- `output/pig_route.gpx` — GPX 1.1 ready for Garmin/Strava import
- `output/pig_route.html` — interactive Folium map showing the snapped route
  (blue) overlaid with the idealized pig outline (red dashed)

The prototype calls the public OSRM demo server at
`router.project-osrm.org`. There is a 1.1 s delay between requests; for heavy
use, swap `BASE_URL` in `osrm_client.py` for a self-hosted OSRM container with
the foot profile and a Geofabrik OSM extract.

### Corporate SSL inspection (macOS)

If `requests.exceptions.SSLError: certificate verify failed` shows up, your
network is doing TLS inspection (Netskope, Zscaler, etc.) and the inspection
root CA is in your macOS keychain but not in certifi. Pass `--ca-bundle keychain`
to auto-export the keychain to a temp PEM and use that for verification:

```
python main.py --lat 37.7530 --lon -122.4830 --distance 10.0 --ca-bundle keychain
```

### Picking a center and distance

Street snapping inflates the routed distance well above the shape's geometric
perimeter, especially around the pig's leg "spikes" which force out-and-back
detours. Empirically:

- **Grid neighborhoods (Sunset, Richmond, Manhattan):** converges within ±10%
  for ~10 km targets (a single rescaling pass; we use 5 by default).
- **Dense/hilly downtown (SOMA, Civic Center):** the leg spikes get warped into
  multi-block loops and you need bigger targets (~15 km+) for the shape to
  stay recognizable.
- **Realistic minimum:** the pig has 1.4-unit-tall legs; for those to map to
  real out-and-back leg routing, scale should be ≥ ~100 m/unit, which means
  the shape spans ~1.2 km × 0.55 km and routes 8 km+ on most street grids.

## Pipeline

1. Pig outline defined in `pig_shape.py` as ordered (x, y) waypoints.
2. Resample to N waypoints evenly spaced along the perimeter.
3. Project onto (lat, lon) around a chosen center, scaled in meters per unit.
4. Single OSRM `/route/v1/foot/` request with all waypoints → snapped polyline.
5. Compare routed distance to target; multiply scale by `target/actual` and
   re-route. Two or three iterations usually converge within ±3%.
6. Emit GPX 1.1 (`<rte>/<rtept>` + `<trk>/<trkpt>`) and a Folium HTML preview.

## Phase 2 — iOS app (TBD)

SwiftUI + MapKit. Pick start point, target distance, shape; preview on map;
export GPX via share sheet. Will likely call a small FastAPI service that
proxies a self-hosted OSRM.
