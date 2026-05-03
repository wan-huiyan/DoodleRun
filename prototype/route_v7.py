"""Shape-aware route generator for v7 redesigned shapes.

Core algorithm follows the gps-art-tangled-trace-fix skill recipe:
  1. Anti-revisit edge penalty in the Dijkstra weight (single biggest visual win)
  2. Few waypoints (we already have 12-15 anchors per shape — no resampling)
  3. Visvalingam-Whyatt simplification of the routed polyline at ~80m

The cost function combines:
  C1 = remaining haversine distance from v to segment endpoint (progress)
  C2 = edge length (travel cost / discourage U-turns)
  C3 = perpendicular distance from edge midpoint to the target outline segment
  + revisit_penalty if this edge has already been used in an earlier segment

Renders TWO PNGs per route:
  - basemap-FREE big PNG (the skill Step 0 — see what's actually traced)
  - basemap overlay PNG (so the user can see real streets)
"""

from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import matplotlib.pyplot as plt
import networkx as nx
import osmnx as ox
from simplification.cutil import simplify_coords_vw

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from cat_shape import CAT_OUTLINE
from chicken_shape import CHICKEN_OUTLINE
from dino_shape import DINO_OUTLINE
from dog_shape import DOG_OUTLINE
from pig_shape import PIG_OUTLINE
from shape_utils import outline_perimeter

LatLon = Tuple[float, float]   # (lat, lon)


@dataclass
class City:
    name: str
    lat: float
    lon: float


CITIES = [
    City("St Albans", 51.7520, -0.3360),
    City("Milton Keynes", 52.0406, -0.7594),
    City("Isle of Dogs", 51.4946, -0.0205),
]

SHAPES = {
    "pig": PIG_OUTLINE,
    "cat": CAT_OUTLINE,
    "dog": DOG_OUTLINE,
    "dino": DINO_OUTLINE,
    "chicken": CHICKEN_OUTLINE,
}


# ---------- geometry helpers ----------

EARTH_RADIUS_M = 6_371_000.0


def haversine(p1: LatLon, p2: LatLon) -> float:
    lat1, lon1 = p1
    lat2, lon2 = p2
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def project_outline(
    outline: Sequence[Tuple[float, float]],
    center_lat: float,
    center_lon: float,
    target_perimeter_m: float,
) -> List[LatLon]:
    """Project shape-unit (x, y) outline to (lat, lon) so its real-world
    perimeter equals target_perimeter_m, centered on (center_lat, center_lon).

    Y is up in shape space. Latitude increases northward.
    """
    perim_units = outline_perimeter(list(outline))
    m_per_unit = target_perimeter_m / perim_units

    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2

    m_per_lat = 111_320.0
    m_per_lon = m_per_lat * math.cos(math.radians(center_lat))

    out: List[LatLon] = []
    for x, y in outline:
        dx_m = (x - cx) * m_per_unit
        dy_m = (y - cy) * m_per_unit
        lat = center_lat + dy_m / m_per_lat
        lon = center_lon + dx_m / m_per_lon
        out.append((lat, lon))
    return out


def point_to_segment_distance_m(p: LatLon, a: LatLon, b: LatLon) -> float:
    """Approximate geodesic distance from p to segment ab using local-flat
    projection (good enough for routing-scale distances)."""
    lat0 = (a[0] + b[0]) / 2
    m_per_lat = 111_320.0
    m_per_lon = m_per_lat * math.cos(math.radians(lat0))

    ax = (a[1] - p[1]) * m_per_lon
    ay = (a[0] - p[0]) * m_per_lat
    bx = (b[1] - p[1]) * m_per_lon
    by = (b[0] - p[0]) * m_per_lat

    vx, vy = bx - ax, by - ay
    seg_len2 = vx * vx + vy * vy
    if seg_len2 == 0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * vx + ay * vy) / seg_len2))
    cx, cy = ax + t * vx, ay + t * vy
    return math.hypot(cx, cy)


# ---------- shape-aware routing ----------

def shape_aware_route(
    G: nx.MultiDiGraph,
    outline_latlon: Sequence[LatLon],
    *,
    alpha: float = 0.0,
    beta: float = 1.0,
    gamma: float = 4.0,
    revisit_penalty_m: float = 5000.0,
) -> List[LatLon]:
    """Trace the outline on the road graph using segment-by-segment Dijkstra
    with a Waschk-Krüger-inspired cost + anti-revisit edge penalty.

    Default coefficients chosen per the skill:
      beta = 1 (use real edge length as base unit, in metres)
      gamma = 12 (shape deviation dominates so the router hugs the outline)
      alpha = 0 (don't force progress — the segment endpoint is the next anchor)
      revisit_penalty_m = 4000 (well above any plausible detour)
    """
    visited_edge_keys: set = set()
    full_polyline: List[LatLon] = []

    # Pre-compute nearest graph nodes for each anchor.
    xs = [p[1] for p in outline_latlon]   # lon
    ys = [p[0] for p in outline_latlon]   # lat
    anchor_nodes = ox.nearest_nodes(G, xs, ys)

    # Cache node coords for fast lookup inside the weight closure.
    node_coords = {n: (G.nodes[n]["y"], G.nodes[n]["x"]) for n in G.nodes()}

    n_segments_failed = 0
    for i in range(len(outline_latlon) - 1):
        seg_start = outline_latlon[i]
        seg_end = outline_latlon[i + 1]
        u_node = anchor_nodes[i]
        v_node = anchor_nodes[i + 1]

        if u_node == v_node:
            continue

        def weight_fn(u, v, edge_data, _ss=seg_start, _se=seg_end):
            data = edge_data[0] if isinstance(edge_data, dict) and 0 in edge_data else edge_data
            length = data.get("length", 0.0) if isinstance(data, dict) else 0.0

            uy, ux = node_coords[u]
            vy, vx = node_coords[v]
            mid = ((uy + vy) / 2, (ux + vx) / 2)
            dev_m = point_to_segment_distance_m(mid, _ss, _se)

            cost = beta * length + gamma * dev_m
            if alpha:
                cost += alpha * haversine((vy, vx), _se)

            key = (u, v) if u < v else (v, u)
            if key in visited_edge_keys:
                cost += revisit_penalty_m
            return cost

        try:
            node_path = nx.shortest_path(G, u_node, v_node, weight=weight_fn)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            n_segments_failed += 1
            continue

        for a, b in zip(node_path, node_path[1:]):
            key = (a, b) if a < b else (b, a)
            visited_edge_keys.add(key)

        seg_polyline = [node_coords[n] for n in node_path]
        if full_polyline and full_polyline[-1] == seg_polyline[0]:
            full_polyline.extend(seg_polyline[1:])
        else:
            full_polyline.extend(seg_polyline)

    if n_segments_failed:
        print(f"      ! {n_segments_failed} segment(s) failed to route")
    return full_polyline


def vw_simplify_latlon(polyline: Sequence[LatLon], tol_m: float = 80.0) -> List[LatLon]:
    if len(polyline) < 4 or tol_m <= 0:
        return list(polyline)
    lat0 = sum(p[0] for p in polyline) / len(polyline)
    m_per_lat = 111_320.0
    m_per_lon = m_per_lat * math.cos(math.radians(lat0))
    lat_o, lon_o = polyline[0]
    xy = [
        [(lon - lon_o) * m_per_lon, (lat - lat_o) * m_per_lat]
        for lat, lon in polyline
    ]
    simplified = simplify_coords_vw(xy, tol_m * tol_m)
    return [
        (lat_o + y / m_per_lat, lon_o + x / m_per_lon)
        for x, y in simplified
    ]


def polyline_length_m(polyline: Sequence[LatLon]) -> float:
    return sum(haversine(a, b) for a, b in zip(polyline, polyline[1:]))


# ---------- rendering ----------

def render_basemap_free(
    polyline: Sequence[LatLon],
    waypoints: Sequence[LatLon],
    out_path: Path,
    title: str,
) -> None:
    fig, ax = plt.subplots(figsize=(11, 11), dpi=130)

    pl_lat = [p[0] for p in polyline]
    pl_lon = [p[1] for p in polyline]
    ax.plot(pl_lon, pl_lat, color="#1f77b4", linewidth=3.5,
            solid_capstyle="round", label="routed (snapped to streets)")

    wp_lat = [p[0] for p in waypoints]
    wp_lon = [p[1] for p in waypoints]
    ax.plot(wp_lon, wp_lat, color="#d62728", linewidth=2.5,
            linestyle="--", label="ideal outline")
    ax.scatter(wp_lon, wp_lat, color="#d62728", s=40, zorder=5)

    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title(title, fontsize=14, weight="bold")
    ax.legend(loc="upper right", fontsize=11)
    ax.grid(True, linestyle=":", alpha=0.3)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def render_with_basemap(
    G: nx.MultiDiGraph,
    polyline: Sequence[LatLon],
    waypoints: Sequence[LatLon],
    out_path: Path,
    title: str,
) -> None:
    fig, ax = ox.plot_graph(
        G,
        node_size=0,
        edge_color="#cccccc",
        edge_linewidth=0.5,
        bgcolor="white",
        show=False,
        close=False,
        figsize=(11, 11),
    )

    pl_lat = [p[0] for p in polyline]
    pl_lon = [p[1] for p in polyline]
    ax.plot(pl_lon, pl_lat, color="#1f77b4", linewidth=3.5,
            solid_capstyle="round", zorder=3)

    wp_lat = [p[0] for p in waypoints]
    wp_lon = [p[1] for p in waypoints]
    ax.plot(wp_lon, wp_lat, color="#d62728", linewidth=2,
            linestyle="--", zorder=2)
    ax.scatter(wp_lon, wp_lat, color="#d62728", s=40, zorder=4)

    pad_lat = (max(pl_lat) - min(pl_lat)) * 0.05 + 0.001
    pad_lon = (max(pl_lon) - min(pl_lon)) * 0.05 + 0.001
    ax.set_xlim(min(pl_lon) - pad_lon, max(pl_lon) + pad_lon)
    ax.set_ylim(min(pl_lat) - pad_lat, max(pl_lat) + pad_lat)
    ax.set_title(title, fontsize=14, weight="bold")
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------- driver ----------

GRAPH_CACHE_DIR = THIS_DIR.parent / "graph_cache"


def load_or_cache_graph(city: City, radius_m: int) -> nx.MultiDiGraph:
    GRAPH_CACHE_DIR.mkdir(exist_ok=True)
    cache_path = GRAPH_CACHE_DIR / f"{city.name.lower().replace(' ', '_')}_{radius_m}.graphml"
    if cache_path.exists():
        print(f"  loaded graph from cache: {cache_path.name}")
        return ox.load_graphml(cache_path)
    print(f"  fetching OSM walking graph for {city.name} (r={radius_m}m)...")
    t0 = time.time()
    G = ox.graph.graph_from_point((city.lat, city.lon), dist=radius_m,
                                  network_type="walk", simplify=True)
    print(f"  fetched {len(G.nodes())} nodes / {len(G.edges())} edges in {time.time()-t0:.1f}s")
    ox.io.save_graphml(G, cache_path)
    return G


def generate(city: City, animal: str, target_distance_m: float,
             out_dir: Path, radius_m: int = 9000) -> dict:
    G = load_or_cache_graph(city, radius_m)
    outline = SHAPES[animal]
    waypoints = project_outline(outline, city.lat, city.lon, target_distance_m)

    t0 = time.time()
    raw = shape_aware_route(G, waypoints)
    polyline = vw_simplify_latlon(raw, tol_m=80.0)
    elapsed = time.time() - t0

    dist = polyline_length_m(polyline)
    print(f"  routed {animal} @ {city.name}: {dist/1000:.1f}km, "
          f"{len(raw)}→{len(polyline)} pts, {elapsed:.1f}s")

    slug = f"{animal}_{city.name.lower().replace(' ', '_')}"
    title = f"{animal.upper()} @ {city.name}  —  {dist/1000:.1f}km"
    render_basemap_free(polyline, waypoints,
                        out_dir / f"{slug}_pure.png",
                        title + "  (basemap-free)")
    render_with_basemap(G, polyline, waypoints,
                        out_dir / f"{slug}_streets.png",
                        title + "  (with streets)")
    return {"animal": animal, "city": city.name, "distance_m": dist,
            "n_pts": len(polyline)}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--animals", nargs="+", default=list(SHAPES.keys()))
    p.add_argument("--cities", nargs="+", default=[c.name for c in CITIES])
    p.add_argument("--target-km", type=float, default=18.0)
    p.add_argument("--out-dir", default="../route_previews")
    p.add_argument("--radius-m", type=int, default=9000)
    args = p.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cities = [c for c in CITIES if c.name in args.cities]

    results = []
    for city in cities:
        for animal in args.animals:
            print(f"\n[{animal} @ {city.name}]")
            try:
                results.append(generate(city, animal, args.target_km * 1000,
                                        out_dir, radius_m=args.radius_m))
            except Exception as e:
                print(f"  FAILED: {e}")

    print(f"\nGenerated {len(results)} routes → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
