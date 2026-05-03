"""Real-world smoke run for generate_search_v2_multi (Phase 3).

Forces actual osmnx.graph_from_point downloads against the configured
cities so we can validate that Phase-3's perf fix + Optuna multi-variant
search produce: (1) routes inside [0.7×, 1.3×] of target_distance_m,
(2) better fidelity than the Phase-1 baseline (London E14 0.307), and
(3) wall-clock under 5 min/city.

Outputs:

    samples/v2_smoke/<city>_<animal>_search.geojson — polyline + waypoints
    samples/v2_smoke/<city>_<animal>_search.png    — matplotlib + basemap
    samples/v2_smoke/summary_v2_multi.json         — distance/fidelity/elapsed

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

import optuna  # noqa: E402

# Suppress per-trial INFO logs from Optuna; the smoke prints its own
# per-variant summary.
optuna.logging.set_verbosity(optuna.logging.WARNING)

from route_generator import generate_search_v2_multi  # noqa: E402
from shapes import SHAPE_VARIANTS  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "samples" / "v2_smoke"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Phase-5 smoke targets: England only. The user runs these IRL, so we pick
# areas they can actually drive to + run from. Mix of grid (Milton Keynes),
# suburban-radial (St Albans, Hemel), and Thames-bend (Isle of Dogs, Barnes,
# Richmond) — the river bends form natural curves that align with animal
# silhouettes in ways a pure grid cannot.
CITIES = [
    ("st_albans",     "St Albans",          51.7520,  -0.3360),
    ("milton_keynes", "Milton Keynes grid", 52.0406,  -0.7594),
    ("hemel",         "Hemel Hempstead",    51.7526,  -0.4707),
    ("isle_of_dogs",  "Isle of Dogs (Thames bend)", 51.4996, -0.0204),
    ("barnes_bend",   "Barnes Thames bend", 51.4720,  -0.2370),
    ("richmond",      "Richmond Thames",    51.4613,  -0.3037),
]
ANIMAL = "pig"
N_TRIALS = 30                 # TPE converges by ~20; 30 leaves headroom
TIMEOUT_S_PER_VARIANT = 60.0
MAX_VARIANTS = 2              # canonical + 1 quickdraw exemplar
# Tighter scale band so most trials land in the soft band [14, 26] km
# instead of being pruned at the 1.5× hard cap. Plan §3.5 calibrates the
# 1.3× perimeter heuristic for 20 km targets, so factor ∈ [0.7, 1.3]
# brackets that comfortably without letting trials shrink to ~13 km.
SCALE_FACTOR_MIN = 0.7        # raised from 0.5 — Phase-3 SF landed at 13 km
SCALE_FACTOR_MAX = 1.3
HARD_CAP_FACTOR = 1.5         # prune anything > 30 km for a 20 km target
SOFT_PENALTY_WEIGHT = 0.5     # raised from 0.3 — push distance closer to target


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
    variants_full = SHAPE_VARIANTS[ANIMAL]
    variants = variants_full[:MAX_VARIANTS]
    print(f"Animal={ANIMAL!r}: using {len(variants)}/{len(variants_full)} variants "
          f"(canonical first, then quickdraw); n_trials={N_TRIALS} per variant")
    for slug, name, lat, lon in CITIES:
        print(f"\n=== {name} @ ({lat:.4f}, {lon:.4f}) ===")
        t0 = time.perf_counter()
        try:
            r = generate_search_v2_multi(
                variants, lat, lon,
                target_distance_m=20_000,
                graph_radius_m=15_000,
                n_trials=N_TRIALS,
                timeout_s=TIMEOUT_S_PER_VARIANT,
                scale_factor_min=SCALE_FACTOR_MIN,
                scale_factor_max=SCALE_FACTOR_MAX,
                hard_cap_factor=HARD_CAP_FACTOR,
                soft_penalty_weight=SOFT_PENALTY_WEIGHT,
            )
        except Exception as exc:
            print(f"  FAILED: {exc.__class__.__name__}: {exc}")
            summary.append({"slug": slug, "city": name, "error": str(exc)})
            continue
        elapsed = time.perf_counter() - t0
        print(f"  variant={r.best_params.get('variant_index')} "
              f"distance={r.distance_m / 1000:.2f}km score={r.fidelity:.4f}  "
              f"({elapsed:.1f}s)")
        if r.fidelity_breakdown:
            print(f"  breakdown={r.fidelity_breakdown}")

        gj = _polyline_to_geojson(r.polyline, r.waypoints,
                                  name=f"{name} {ANIMAL}",
                                  distance_m=r.distance_m,
                                  fidelity=r.fidelity)
        gj_path = OUT_DIR / f"{slug}_{ANIMAL}_search.geojson"
        with open(gj_path, "w") as f:
            json.dump(gj, f, indent=2)
        html = _try_render_png(gj_path, OUT_DIR / f"{slug}_{ANIMAL}_search.png")
        # Matplotlib PNG (preferred — committed for review).
        try:
            from render_preview_png import render_geojson
            png_path = OUT_DIR / f"{slug}_{ANIMAL}_search.png"
            render_geojson(gj_path, png_path)
            print(f"  png written → {png_path.name}")
        except Exception as exc:
            print(f"  [warn] matplotlib PNG render failed: {exc}")
            png_path = None
        # Also drop a big basemap-free version — the OSM tiles eat most of
        # the canvas and make it impossible to judge whether the trace
        # actually looks like the animal. The big version is what we use
        # to verify visual quality.
        try:
            from iter_v2 import _render_big_clean
            big_path = OUT_DIR / f"{slug}_{ANIMAL}_search_big.png"
            _render_big_clean(gj_path, big_path)
            print(f"  big png   → {big_path.name}")
        except Exception as exc:
            print(f"  [warn] big PNG render failed: {exc}")
        summary.append({
            "slug": slug, "city": name, "lat": lat, "lon": lon,
            "distance_m": r.distance_m,
            "score": r.fidelity,
            "fidelity_breakdown": r.fidelity_breakdown,
            "best_params": r.best_params,
            "elapsed_s": elapsed,
            "geojson": gj_path.name,
            "png": png_path.name if png_path else None,
            "html_preview": html.name if html else None,
        })

    sum_path = OUT_DIR / "summary_v2_multi.json"
    with open(sum_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary written to {sum_path}")


if __name__ == "__main__":
    main()
