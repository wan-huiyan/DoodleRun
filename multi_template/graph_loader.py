"""Load an OSMnx street graph and precompute per-edge attrs.

The router calls a cost function per edge during Dijkstra, so we cache the
per-edge bearing / midpoint / length once at graph load. Without this, a
30 km MultiDiGraph callable-weight Dijkstra is 30-90s; with it, 2-3s.
"""
from __future__ import annotations

import math
import os
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import networkx as nx
import numpy as np
import osmnx as ox

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)
ox.settings.use_cache = True
ox.settings.log_console = False


def _ensure_ssl_bundle() -> None:
    """On macOS behind Netskope/corporate TLS-MITM, requests fails against
    overpass. Build a one-shot bundle from the system keychain on first call.
    """
    bundle = Path("/tmp/doodlerun_ca_bundle.pem")
    if not bundle.exists():
        import subprocess
        try:
            chunks = []
            for cn in ("ca.mediamonks.goskope.com", "Netskope", "certadmin"):
                try:
                    out = subprocess.check_output(
                        ["security", "find-certificate", "-a", "-c", cn, "-p",
                         "/Library/Keychains/System.keychain"],
                        stderr=subprocess.DEVNULL,
                    )
                    chunks.append(out)
                except subprocess.CalledProcessError:
                    pass
            import certifi
            chunks.append(Path(certifi.where()).read_bytes())
            bundle.write_bytes(b"".join(chunks))
        except Exception as e:
            print(f"  warn: could not build CA bundle: {e}")
            return
    os.environ.setdefault("SSL_CERT_FILE", str(bundle))
    os.environ.setdefault("REQUESTS_CA_BUNDLE", str(bundle))


_ensure_ssl_bundle()

EARTH_R_M = 6_371_008.8


def _haversine_m(lat1, lon1, lat2, lon2):
    rl1, rl2 = math.radians(lat1), math.radians(lat2)
    dlat = rl2 - rl1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rl1) * math.cos(rl2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(a))


def _bearing_rad(lat1, lon1, lat2, lon2):
    rl1, rl2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(rl2)
    y = math.cos(rl1) * math.sin(rl2) - math.sin(rl1) * math.cos(rl2) * math.cos(dlon)
    return math.atan2(x, y)  # [-pi, pi], 0 = north


@dataclass
class StreetGraph:
    G: nx.MultiDiGraph
    center_lat: float
    center_lon: float
    radius_m: int

    def cache_path(self) -> Path:
        key = f"{self.center_lat:.4f}_{self.center_lon:.4f}_{self.radius_m}.pkl"
        return CACHE_DIR / key


def _precompute_edge_attrs(G: nx.MultiDiGraph) -> None:
    """Write `_bear_rad`, `_mid_lat`, `_mid_lon`, `_length_m` to every edge.

    OSMnx already writes `length` (m) and `bearing` (deg from north). We
    duplicate into radians for cost-function speed.
    """
    nodes = G.nodes
    for u, v, key, data in G.edges(keys=True, data=True):
        u_lat = nodes[u]["y"]; u_lon = nodes[u]["x"]
        v_lat = nodes[v]["y"]; v_lon = nodes[v]["x"]
        if "length" in data and data["length"] is not None:
            length_m = float(data["length"])
        else:
            length_m = _haversine_m(u_lat, u_lon, v_lat, v_lon)
        bear = _bearing_rad(u_lat, u_lon, v_lat, v_lon)
        data["_bear_rad"] = bear
        data["_length_m"] = length_m
        data["_mid_lat"] = (u_lat + v_lat) * 0.5
        data["_mid_lon"] = (u_lon + v_lon) * 0.5


def load_graph(
    center_lat: float,
    center_lon: float,
    radius_m: int = 15_000,
    network_type: str = "walk",
) -> StreetGraph:
    """Load (or hit cache for) a street graph centred at (lat, lon).

    walk network is right for GPS-art: it includes pedestrian-only links
    and excludes motorway-only stretches.
    """
    sg = StreetGraph(nx.MultiDiGraph(), center_lat, center_lon, radius_m)
    cache = sg.cache_path()
    if cache.exists():
        with cache.open("rb") as f:
            sg.G = pickle.load(f)
        return sg
    print(f"  fetching OSM graph @ ({center_lat:.4f},{center_lon:.4f}) r={radius_m}m...")
    G = ox.graph_from_point(
        (center_lat, center_lon),
        dist=radius_m,
        network_type=network_type,
        simplify=True,
    )
    _precompute_edge_attrs(G)
    with cache.open("wb") as f:
        pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)
    sg.G = G
    return sg


def graph_extents_m(G: nx.MultiDiGraph) -> Tuple[float, float, float, float]:
    """min_lat, min_lon, max_lat, max_lon over node coords."""
    lats = [d["y"] for _, d in G.nodes(data=True)]
    lons = [d["x"] for _, d in G.nodes(data=True)]
    return min(lats), min(lons), max(lats), max(lons)


if __name__ == "__main__":
    sg = load_graph(51.7520, -0.3360, radius_m=4000)  # St Albans (small probe)
    print(f"loaded {sg.G.number_of_nodes()} nodes, {sg.G.number_of_edges()} edges")
    sample_edge = next(iter(sg.G.edges(data=True)))
    print(f"sample edge attrs: bearing={math.degrees(sample_edge[2]['_bear_rad']):.1f}°, "
          f"length={sample_edge[2]['_length_m']:.1f}m")
