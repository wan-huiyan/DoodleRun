"""Real-world smoke run for generate_v2.

Forces actual osmnx.graph_from_point downloads against three cities so
we can visually validate that Phase 1's W-K shape-aware router produces
a route that hugs the outline (not spaghetti). Outputs:

    samples/v2_smoke/<city>_pig.geojson      — full polyline + waypoints
    samples/v2_smoke/<city>_pig.png          — folium PNG (best-effort)
    samples/v2_smoke/summary.json            — distance + fidelity per city

Run:  ../.venv/bin/python smoke_v2.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Allow running from prototype/ without packaging.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# OSMnx hits Overpass over HTTPS — on corp-proxy macOS the keychain CA bundle
# is needed. Wire the existing helper from the legacy OSRM client into the env
# vars that requests + urllib3 inside osmnx will pick up.
from osrm_client import macos_keychain_bundle  # noqa: E402

if sys.platform == "darwin" and os.environ.get("DOODLERUN_TRUST_KEYCHAIN", "1") == "1":
    try:
        bundle = macos_keychain_bundle()
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("CURL_CA_BUNDLE", bundle)
    except Exception as _exc:
        print(f"[warn] could not export keychain CA bundle: {_exc}")

from route_generator import generate_v2  # noqa: E402
from shapes import SHAPES  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "samples" / "v2_smoke"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CITIES = [
    ("london_e14", "London E14",  51.5074,  -0.0148),
    ("sf_sunset",  "SF Sunset",   37.7559, -122.4828),
    ("manhattan",  "Manhattan",   40.7831,  -73.9712),
]


def _polyline_to_geojson(polyline, waypoints, *, name: str, distance_m: float, fidelity: float) -> dict:
    return {
        "type": "FeatureCollection",
        "name": name,
        "properties": {"distance_m": distance_m, "fidelity": fidelity},
        "features": [
            {
                "type": "Feature",
                "properties": {"role": "route_polyline"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [(lon, lat) for lat, lon in polyline],
                },
            },
            {
                "type": "Feature",
                "properties": {"role": "shape_waypoints"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [(lon, lat) for lat, lon in waypoints],
                },
            },
        ],
    }


def _try_render_png(geojson_path: Path, png_path: Path):
    """Best-effort folium → PNG (browser screenshot needed for true PNG)."""
    try:
        import folium
        with open(geojson_path) as f:
            gj = json.load(f)
        # Compute centroid for the map
        coords = gj["features"][0]["geometry"]["coordinates"]
        lat = sum(c[1] for c in coords) / len(coords)
        lon = sum(c[0] for c in coords) / len(coords)
        m = folium.Map(location=(lat, lon), zoom_start=13, tiles="OpenStreetMap")
        # waypoint outline (idealized) in red
        wp = gj["features"][1]["geometry"]["coordinates"]
        folium.PolyLine([(c[1], c[0]) for c in wp], color="#d62728", weight=2,
                        opacity=0.6, dash_array="6,6").add_to(m)
        # routed polyline in blue
        folium.PolyLine([(c[1], c[0]) for c in coords], color="#1f77b4", weight=4,
                        opacity=0.9).add_to(m)
        html_path = png_path.with_suffix(".html")
        m.save(str(html_path))
        return html_path
    except Exception as exc:
        print(f"  [warn] folium render skipped: {exc}")
        return None


def main():
    summary = []
    for slug, name, lat, lon in CITIES:
        print(f"\n=== {name} @ ({lat:.4f}, {lon:.4f}) ===")
        t0 = time.perf_counter()
        try:
            # Use the per-candidate 15 km graph cap (plan §9). The 30 km
            # SEARCH radius governs candidate placement, not graph load.
            r = generate_v2(SHAPES["pig"], lat, lon,
                            target_distance_m=20_000,
                            graph_radius_m=15_000)
        except Exception as exc:
            print(f"  FAILED: {exc.__class__.__name__}: {exc}")
            summary.append({"slug": slug, "city": name, "error": str(exc)})
            continue
        elapsed = time.perf_counter() - t0
        print(f"  distance={r.distance_m / 1000:.2f} km  fidelity={r.fidelity:.4f}  "
              f"({elapsed:.1f}s)")

        gj = _polyline_to_geojson(r.polyline, r.waypoints,
                                  name=f"{name} pig",
                                  distance_m=r.distance_m,
                                  fidelity=r.fidelity)
        gj_path = OUT_DIR / f"{slug}_pig.geojson"
        with open(gj_path, "w") as f:
            json.dump(gj, f, indent=2)
        html = _try_render_png(gj_path, OUT_DIR / f"{slug}_pig.png")
        summary.append({
            "slug": slug, "city": name, "lat": lat, "lon": lon,
            "distance_m": r.distance_m, "fidelity": r.fidelity,
            "elapsed_s": elapsed, "geojson": str(gj_path.name),
            "html_preview": html.name if html else None,
        })

    sum_path = OUT_DIR / "summary.json"
    with open(sum_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary written to {sum_path}")


if __name__ == "__main__":
    main()
