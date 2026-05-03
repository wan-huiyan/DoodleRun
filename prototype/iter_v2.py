"""Single-city iteration harness for tuning the Phase-5 router.

Targets ONE city + animal so each iteration takes ~2 min instead of the
full smoke's ~15 min. Caches the graph after the first run, so subsequent
runs only re-do the Optuna search.

Usage:
    python iter_v2.py                     # default: St Albans pig
    python iter_v2.py --city isle_of_dogs # other targets in CITY_TABLE
    python iter_v2.py --animal cat        # any of pig/cat/dog/dino/chicken
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from osrm_client import macos_keychain_bundle  # noqa: E402

if sys.platform == "darwin" and os.environ.get("DOODLERUN_TRUST_KEYCHAIN", "1") == "1":
    try:
        bundle = macos_keychain_bundle()
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("CURL_CA_BUNDLE", bundle)
    except Exception:
        pass

import optuna  # noqa: E402
optuna.logging.set_verbosity(optuna.logging.WARNING)

from route_generator import generate_search_v2_multi  # noqa: E402
from shapes import SHAPE_VARIANTS  # noqa: E402

def _simplify_polyline_m(polyline, tol_m: float):
    """Visvalingam-Whyatt simplification of a (lat, lon) polyline.

    Projects to a local equirectangular frame so the tolerance argument is
    in metres (not degrees). Falls back to the input unchanged if the
    `simplification` package isn't installed.
    """
    if len(polyline) < 4 or tol_m <= 0:
        return list(polyline)
    try:
        from simplification.cutil import simplify_coords_vw
    except ImportError:
        return list(polyline)
    import math
    lat0 = sum(p[0] for p in polyline) / len(polyline)
    m_per_lat = 111_320.0
    m_per_lon = m_per_lat * math.cos(math.radians(lat0))
    xy = [[(lon - polyline[0][1]) * m_per_lon,
           (lat - polyline[0][0]) * m_per_lat] for lat, lon in polyline]
    # VW expects an "epsilon" — for VW this is the area threshold of the
    # triangle formed by the point and its neighbours (m²). Squaring the
    # tolerance gives a length-equivalent threshold.
    simplified_xy = simplify_coords_vw(xy, tol_m * tol_m)
    return [(polyline[0][0] + y / m_per_lat,
             polyline[0][1] + x / m_per_lon) for x, y in simplified_xy]


CITY_TABLE = {
    "st_albans":     ("St Albans",                  51.7520,  -0.3360),
    "milton_keynes": ("Milton Keynes grid",         52.0406,  -0.7594),
    "hemel":         ("Hemel Hempstead",            51.7526,  -0.4707),
    "isle_of_dogs":  ("Isle of Dogs (Thames bend)", 51.4996,  -0.0204),
    "barnes_bend":   ("Barnes Thames bend",         51.4720,  -0.2370),
    "richmond":      ("Richmond Thames",            51.4613,  -0.3037),
}

OUT_DIR = Path(__file__).resolve().parent.parent / "samples" / "v2_iter"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--city", default="st_albans", choices=sorted(CITY_TABLE))
    p.add_argument("--animal", default="pig")
    p.add_argument("--trials", type=int, default=30)
    p.add_argument("--variants", type=int, default=2)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--waypoints", type=int, default=15,
                   help="Outline waypoints. 12-18 reads as a clean shape; "
                        "more produces twisty traces that lose recognisability.")
    p.add_argument("--simplify-tol-m", type=float, default=80.0,
                   help="Visvalingam-Whyatt tolerance for polyline simplification "
                        "post-route. 80 m removes ~3-block road-network noise "
                        "without losing animal features.")
    p.add_argument("--tag", default="iter")
    args = p.parse_args()

    name, lat, lon = CITY_TABLE[args.city]
    variants = SHAPE_VARIANTS[args.animal][: args.variants]
    print(f"=== {name} @ ({lat:.4f}, {lon:.4f}) — animal={args.animal!r} "
          f"({args.variants} variant(s), {args.trials} trials each) ===")

    t0 = time.perf_counter()
    r = generate_search_v2_multi(
        variants, lat, lon,
        target_distance_m=20_000,
        graph_radius_m=15_000,
        n_trials=args.trials,
        timeout_s=args.timeout,
        n_waypoints=args.waypoints,
        scale_factor_min=0.7,
        scale_factor_max=1.3,
        hard_cap_factor=1.5,
        soft_penalty_weight=0.5,
    )
    elapsed = time.perf_counter() - t0
    print(f"  variant={r.best_params.get('variant_index')} "
          f"distance={r.distance_m / 1000:.2f}km score={r.fidelity:.4f}  "
          f"({elapsed:.1f}s)")
    if r.fidelity_breakdown:
        print(f"  breakdown={r.fidelity_breakdown}")

    # The route_generator already runs VW simplification at simplify_tol_m
    # (default 80 m) before returning, so what we have here is the trace
    # the user gets. Re-simplifying would be a no-op.
    print(f"  polyline length: {len(r.polyline)} pts")

    slug = f"{args.city}_{args.animal}_{args.tag}"
    polyline_for_display = r.polyline
    gj = {
        "type": "FeatureCollection",
        "name": f"{name} {args.animal}",
        "properties": {"distance_m": r.distance_m, "fidelity": r.fidelity},
        "features": [
            {"type": "Feature", "properties": {"role": "route_polyline"},
             "geometry": {"type": "LineString",
                          "coordinates": [(lon, lat) for lat, lon in polyline_for_display]}},
            {"type": "Feature", "properties": {"role": "shape_waypoints"},
             "geometry": {"type": "LineString",
                          "coordinates": [(lon, lat) for lat, lon in r.waypoints]}},
        ],
    }
    gj_path = OUT_DIR / f"{slug}.geojson"
    with open(gj_path, "w") as f:
        json.dump(gj, f, indent=2)

    try:
        from render_preview_png import render_geojson
        png_path = OUT_DIR / f"{slug}.png"
        render_geojson(gj_path, png_path)
        print(f"  png → {png_path}")
        # Also render a basemap-free, larger version that shows the
        # SHAPE clearly without the OSM tiles eating most of the canvas.
        big_png = OUT_DIR / f"{slug}_big.png"
        _render_big_clean(gj_path, big_png)
        print(f"  big → {big_png}")
    except Exception as exc:
        print(f"  [warn] PNG render failed: {exc}")


def _render_big_clean(gj_path: Path, out_path: Path):
    """Big square plot — route + outline only, no basemap. Lets us judge
    whether the trace LOOKS like the animal without map clutter."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with open(gj_path) as f:
        gj = json.load(f)
    poly = gj["features"][0]["geometry"]["coordinates"]
    wp = gj["features"][1]["geometry"]["coordinates"]
    fig, ax = plt.subplots(figsize=(11, 11), dpi=120)
    ax.plot([c[0] for c in poly], [c[1] for c in poly],
            color="#1f77b4", linewidth=3.5, alpha=0.95,
            label="routed polyline")
    ax.plot([c[0] for c in wp], [c[1] for c in wp],
            color="#d62728", linewidth=2.0, alpha=0.85,
            linestyle="--", label="idealized outline")
    ax.set_aspect("equal", adjustable="datalim")
    name = gj.get("name", gj_path.stem)
    props = gj.get("properties", {})
    title = name + (
        f"  ({props['distance_m'] / 1000:.1f} km, "
        f"fidelity={props.get('fidelity', float('nan')):.3f})"
        if "distance_m" in props else ""
    )
    ax.set_title(title)
    ax.legend(loc="lower right")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
