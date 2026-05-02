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
from osrm_client import macos_keychain_bundle
from route_generator import generate
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
    return p.parse_args()


def main() -> None:
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)

    outline = SHAPES[args.shape]
    name = args.name or f"{args.shape.capitalize()} Run"
    target_m = args.distance * 1000.0
    print(f"Generating {args.shape} route: center=({args.lat}, {args.lon}), "
          f"target={args.distance:.2f} km, waypoints={args.waypoints}")

    verify: object = True
    if args.ca_bundle == "keychain":
        verify = macos_keychain_bundle()
        print(f"  using macOS keychain CA bundle: {verify}")
    elif args.ca_bundle:
        verify = args.ca_bundle

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
    html_path = os.path.join(args.out, f"{args.shape}_route.html")

    write_gpx(gpx_path, result.polyline, name=name,
              description=f"GPS-art {args.shape}, ~{result.distance_m / 1000:.2f} km")
    render(result.polyline, result.waypoints, html_path,
           title=f"{name} — {result.distance_m / 1000:.2f} km")

    print(f"\nDone. Routed distance: {result.distance_m / 1000:.2f} km "
          f"(target {args.distance:.2f} km)")
    print(f"  GPX:  {os.path.abspath(gpx_path)}")
    print(f"  Map:  {os.path.abspath(html_path)}")


if __name__ == "__main__":
    main()
