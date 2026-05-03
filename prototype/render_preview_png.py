"""Render a smoke-output geojson to a PNG preview using matplotlib + contextily.

contextily fetches a basemap tile (OSM) so the preview shows roads
underneath the routed polyline. Falls back to a tile-less plot if the
basemap fetch fails (offline / proxy).

Usage:
    ../.venv/bin/python render_preview_png.py SAMPLES_DIR
        --> writes <city>_pig.png next to each <city>_pig.geojson
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Tuple

# Wire macOS keychain CA bundle so contextily's tile fetches work behind
# corp TLS inspection. Same trick smoke_v2.py uses.
if sys.platform == "darwin" and os.environ.get("DOODLERUN_TRUST_KEYCHAIN", "1") == "1":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from osrm_client import macos_keychain_bundle
        bundle = macos_keychain_bundle()
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("CURL_CA_BUNDLE", bundle)
    except Exception:
        pass


def _xy_to_webmercator(lat: float, lon: float) -> Tuple[float, float]:
    """Convert lat/lon → Web Mercator (EPSG:3857) metres."""
    import math
    x = lon * 20_037_508.34 / 180
    y = math.log(math.tan((90 + lat) * math.pi / 360)) / math.pi * 20_037_508.34
    return x, y


def render_geojson(geojson_path: Path, out_path: Path | None = None,
                   *, with_basemap: bool = True) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with open(geojson_path) as f:
        gj = json.load(f)

    poly = gj["features"][0]["geometry"]["coordinates"]   # [(lon, lat), ...]
    wp = gj["features"][1]["geometry"]["coordinates"]

    poly_xy = [_xy_to_webmercator(lat, lon) for lon, lat in poly]
    wp_xy = [_xy_to_webmercator(lat, lon) for lon, lat in wp]

    fig, ax = plt.subplots(figsize=(10, 10), dpi=120)
    ax.plot([p[0] for p in poly_xy], [p[1] for p in poly_xy],
            color="#1f77b4", linewidth=2.5, alpha=0.9, label="routed polyline",
            zorder=3)
    ax.plot([p[0] for p in wp_xy], [p[1] for p in wp_xy],
            color="#d62728", linewidth=1.4, alpha=0.7, linestyle="--",
            label="idealized outline", zorder=4)
    ax.set_aspect("equal", adjustable="datalim")
    ax.legend(loc="lower right", framealpha=0.85)
    name = gj.get("name", geojson_path.stem)
    props = gj.get("properties", {})
    title = name
    if "distance_m" in props:
        title += f"  ({props['distance_m'] / 1000:.1f} km, fidelity={props.get('fidelity', float('nan')):.3f})"
    ax.set_title(title)
    ax.set_xticks([])
    ax.set_yticks([])

    if with_basemap:
        try:
            import contextily as cx  # type: ignore[import-not-found]
            cx.add_basemap(ax, crs="EPSG:3857",
                           source=cx.providers.OpenStreetMap.Mapnik)
        except Exception as exc:
            print(f"  [warn] basemap skipped: {exc}")

    if out_path is None:
        out_path = geojson_path.with_suffix(".png")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("samples_dir", type=Path)
    p.add_argument("--no-basemap", action="store_true",
                   help="Skip the contextily basemap (faster, offline-friendly)")
    args = p.parse_args()

    if not args.samples_dir.is_dir():
        sys.exit(f"Not a directory: {args.samples_dir}")

    for gj_path in sorted(args.samples_dir.glob("*.geojson")):
        out = render_geojson(gj_path, with_basemap=not args.no_basemap)
        print(f"  wrote {out.name}")


if __name__ == "__main__":
    main()
