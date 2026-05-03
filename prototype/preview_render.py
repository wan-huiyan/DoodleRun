"""Render a preview PNG showing target outline + routed polyline + base map."""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Tuple

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import osmnx as ox

from .area_scorer import latlon_to_xy
from .multi_template_search import Candidate


def render_candidate(
    handle,
    candidate: Candidate,
    out_path: Path,
    *,
    title: str | None = None,
    pad_m: float = 1500.0,
):
    """Plot the OSMnx graph + target outline + routed polyline."""
    G = handle.G
    ref_lat = candidate.center_lat
    ref_lon = candidate.center_lon

    target_xy = latlon_to_xy(candidate.projected, ref_lat, ref_lon)
    route_xy = latlon_to_xy(candidate.route, ref_lat, ref_lon) if candidate.route else []

    # Subset graph nodes for plotting bounds
    xs = [p[0] for p in target_xy] + [p[0] for p in route_xy]
    ys = [p[1] for p in target_xy] + [p[1] for p in route_xy]
    if not xs:
        return
    minx, maxx = min(xs) - pad_m, max(xs) + pad_m
    miny, maxy = min(ys) - pad_m, max(ys) + pad_m

    fig, ax = plt.subplots(figsize=(10, 10))

    # Draw streets in gray as line segments
    m_per_deg_lat = 6_371_000.0 * math.pi / 180.0
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(ref_lat))
    for u, v, data in G.edges(data=True):
        if 'geometry' in data:
            xs2, ys2 = data['geometry'].xy
            x_m = [(lon - ref_lon) * m_per_deg_lon for lon in xs2]
            y_m = [(lat - ref_lat) * m_per_deg_lat for lat in ys2]
        else:
            x_m = [
                (G.nodes[u]['x'] - ref_lon) * m_per_deg_lon,
                (G.nodes[v]['x'] - ref_lon) * m_per_deg_lon,
            ]
            y_m = [
                (G.nodes[u]['y'] - ref_lat) * m_per_deg_lat,
                (G.nodes[v]['y'] - ref_lat) * m_per_deg_lat,
            ]
        # Skip if entirely outside bbox
        if max(x_m) < minx or min(x_m) > maxx or max(y_m) < miny or min(y_m) > maxy:
            continue
        ax.plot(x_m, y_m, color='#bbbbbb', linewidth=0.5, zorder=1)

    # Target outline (the projected template) in pale orange, dashed
    if target_xy:
        tx = [p[0] for p in target_xy]
        ty = [p[1] for p in target_xy]
        ax.plot(tx, ty, color='#ffa84a', linewidth=2.0, linestyle='--',
                alpha=0.65, label='target outline', zorder=2)

    # Routed polyline in red
    if route_xy:
        rx = [p[0] for p in route_xy]
        ry = [p[1] for p in route_xy]
        ax.plot(rx, ry, color='#d6224c', linewidth=2.4, label='route', zorder=3)
        ax.plot(rx[0], ry[0], 'o', color='#1a8d2c', markersize=8, label='start', zorder=4)

    ax.set_aspect('equal')
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_xlabel('east (m)')
    ax.set_ylabel('north (m)')
    if title:
        ax.set_title(title)
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches='tight')
    plt.close(fig)


__all__ = ['render_candidate']
