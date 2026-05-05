"""CLI entrypoint: generate an animal-shaped running route around a center point.

Example:
    python main.py --shape pig --lat 37.7530 --lon -122.4830 --distance 10.0

Outputs (into --out dir):
    <shape>_route.gpx   — GPX 1.1 file ready for Garmin/Strava
    <shape>_route.html  — Folium map preview
"""

from __future__ import annotations

import argparse
import os

from gpx_export import write_gpx
from kml_export import write_kml
from osrm_client import macos_keychain_bundle
from preview import (
    project_outline,
    render_preview_html,
    render_shape_png,
    scale_for_distance,
)
from route_generator import generate, generate_search
from shapes import SHAPES
from visualize import render


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate an animal-shaped running route.")
    p.add_argument("--shape", choices=sorted(SHAPES.keys()), default="pig",
                   help="Which animal outline to draw")
    p.add_argument("--lat", type=float, default=37.7530, help="Center latitude")
    p.add_argument("--lon", type=float, default=-122.4830, help="Center longitude")
    p.add_argument("--distance", type=float, default=10.0, help="Target distance in km")
    p.add_argument("--waypoints", type=int, default=40,
                   help="Number of resampled waypoints sent to OSRM (max ~80 on demo server)")
    p.add_argument("--iterations", type=int, default=5,
                   help="Rescaling iterations to hit target distance")
    p.add_argument("--out", default="../output", help="Output directory")
    p.add_argument("--name", default=None,
                   help="Route name embedded in GPX (default: '<Shape> Run')")
    p.add_argument("--ca-bundle", default=None,
                   help="Path to a CA bundle PEM. Use 'keychain' on macOS to "
                        "auto-export the system+login keychain (needed when "
                        "behind corporate SSL inspection). Default: certifi.")
    p.add_argument("--search-radius-km", type=float, default=None,
                   help="Enable fidelity-first search: try multiple candidate "
                        "centers within this radius and pick the one that "
                        "traces the shape most accurately. Distance becomes a "
                        "hint, not a target.")
    p.add_argument("--candidates", type=int, default=5,
                   help="With --search-radius-km, number of candidate centers "
                        "to try. Default 5 (1 seed + 4 ring positions).")
    p.add_argument("--scales", type=int, default=3,
                   help="With --search-radius-km, number of scale candidates "
                        "per center (geometrically spaced 0.5x..1.6x of the "
                        "scale that would hit --distance). Default 3.")
    p.add_argument("--preview-only", action="store_true",
                   help="Skip OSRM entirely. Render the idealized shape outline "
                        "as a PNG (unit space) and an HTML map (projected at "
                        "--lat/--lon, --distance-sized). Use for fast shape "
                        "iteration without burning rate-limited OSRM requests.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)

    outline = SHAPES[args.shape]
    name = args.name or f"{args.shape.capitalize()} Run"
    target_m = args.distance * 1000.0

    if args.preview_only:
        png_path = os.path.join(args.out, f"{args.shape}_preview.png")
        html_path = os.path.join(args.out, f"{args.shape}_preview.html")
        scale = scale_for_distance(outline, target_m)
        waypoints = project_outline(outline, args.lat, args.lon, scale)
        render_shape_png(outline, png_path, title=name)
        render_preview_html(waypoints, html_path,
                            title=f"{name} preview — {args.distance:.1f} km nominal "
                                  f"(no street snap)")
        print(f"Preview only: scale={scale:.1f} m/unit at "
              f"({args.lat:.4f}, {args.lon:.4f})")
        print(f"  PNG:  {os.path.abspath(png_path)}")
        print(f"  Map:  {os.path.abspath(html_path)}")
        return

    print(f"Generating {args.shape} route: center=({args.lat}, {args.lon}), "
          f"target={args.distance:.2f} km, waypoints={args.waypoints}")

    verify: object = True
    if args.ca_bundle == "keychain":
        verify = macos_keychain_bundle()
        print(f"  using macOS keychain CA bundle: {verify}")
    elif args.ca_bundle:
        verify = args.ca_bundle

    if args.search_radius_km is not None:
        result = generate_search(
            outline=outline,
            center_lat=args.lat,
            center_lon=args.lon,
            target_distance_m=target_m,
            search_radius_km=args.search_radius_km,
            n_candidates=args.candidates,
            n_scales=args.scales,
            n_waypoints=args.waypoints,
            verify=verify,
        )
    else:
        result = generate(
            outline=outline,
            center_lat=args.lat,
            center_lon=args.lon,
            target_distance_m=target_m,
            n_waypoints=args.waypoints,
            max_iterations=args.iterations,
            verify=verify,
        )

    gpx_path = os.path.join(args.out, f"{args.shape}_route.gpx")
    kml_path = os.path.join(args.out, f"{args.shape}_route.kml")
    html_path = os.path.join(args.out, f"{args.shape}_route.html")

    desc = f"GPS-art {args.shape}, ~{result.distance_m / 1000:.2f} km"
    write_gpx(gpx_path, result.polyline, name=name, description=desc)
    write_kml(kml_path, result.polyline, name=name, description=desc)
    render(result.polyline, result.waypoints, html_path,
           title=f"{name} — {result.distance_m / 1000:.2f} km")

    print(f"\nDone. Routed distance: {result.distance_m / 1000:.2f} km "
          f"(target {args.distance:.2f} km)")
    print(f"  Fidelity: {result.fidelity:.4f}  (lower=better, 0=perfect tracing)")
    print(f"  Center:   ({result.center_lat:.4f}, {result.center_lon:.4f})  "
          f"scale={result.scale_m_per_unit:.1f} m/unit")
    print(f"  GPX:  {os.path.abspath(gpx_path)}")
    print(f"  KML:  {os.path.abspath(kml_path)}")
    print(f"  Map:  {os.path.abspath(html_path)}")


if __name__ == "__main__":
    main()
