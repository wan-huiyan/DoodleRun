"""Render an idealized shape outline without calling OSRM.

Two outputs the design loop cares about:
- PNG of the bare shape in unit space (no map, no axes) — the canonical view
  for judging "does this read as a pig?".
- HTML map of the projected outline at a real lat/lon — shows the geographic
  scale a runner would actually trace, but no street snapping.

Matplotlib is imported lazily so the prototype keeps a small server-side
dependency footprint (only `--preview-only` users need it).
"""

from __future__ import annotations

import math
from typing import List, Tuple

import folium

from shape_utils import Point, bounding_box, outline_perimeter

EARTH_M_PER_DEG_LAT = 111_320.0


def project_outline(
    outline: List[Point],
    center_lat: float,
    center_lon: float,
    scale_m_per_unit: float,
) -> List[Tuple[float, float]]:
    """Same projection as route_generator.project_shape, duplicated here so
    preview has zero dependency on the routing pipeline."""
    min_x, min_y, max_x, max_y = bounding_box(outline)
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    m_per_lon = EARTH_M_PER_DEG_LAT * math.cos(math.radians(center_lat))
    out: List[Tuple[float, float]] = []
    for x, y in outline:
        dx_m = (x - cx) * scale_m_per_unit
        dy_m = (y - cy) * scale_m_per_unit
        out.append((
            center_lat + dy_m / EARTH_M_PER_DEG_LAT,
            center_lon + dx_m / m_per_lon,
        ))
    return out


def scale_for_distance(outline: List[Point], target_distance_m: float) -> float:
    """Same heuristic the router uses to seed its scale grid: route length is
    typically ~1.3x the perimeter once snapped to streets."""
    return (target_distance_m / 1.3) / outline_perimeter(outline)


def render_shape_png(
    outline: List[Point],
    out_path: str,
    title: str = "",
) -> None:
    """Render a unit-space PNG of the shape — the canonical design preview.

    No map tiles, no axes, no resampling. The polyline is drawn exactly as
    declared in the shape file so we're judging the source of truth.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not outline:
        raise ValueError("outline is empty")

    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]

    fig, ax = plt.subplots(figsize=(6, 6), dpi=160)
    # Line-only render: the actual route is a polyline a runner traces, not a
    # filled region. Filled polygons obscure self-intersecting features
    # (curly tails, doubled-back ears) that show up clearly as crossing
    # strokes when only the line is drawn.
    ax.plot(xs, ys, color="#1a73e8", linewidth=3.0, solid_joinstyle="round",
            solid_capstyle="round")
    # Mark start point (== end point) so the trace direction is obvious.
    ax.plot(xs[0], ys[0], "o", color="#137333", markersize=9,
            markeredgecolor="white", markeredgewidth=1.5, zorder=5)
    ax.set_aspect("equal")
    ax.axis("off")
    # Pad so features touching the bounding box (ear tips, tail feathers) don't
    # hug the figure edge.
    min_x, min_y, max_x, max_y = bounding_box(outline)
    pad = max(max_x - min_x, max_y - min_y) * 0.08
    ax.set_xlim(min_x - pad, max_x + pad)
    ax.set_ylim(min_y - pad, max_y + pad)
    if title:
        ax.set_title(title, fontsize=13, pad=10)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white", pad_inches=0.1)
    plt.close(fig)


def render_preview_html(
    waypoints: List[Tuple[float, float]],
    out_path: str,
    title: str = "Shape preview",
) -> None:
    """Folium map showing the projected outline at the user's chosen center.

    No street polyline — this is purely the idealized outline overlaid on a
    real-world tile background to show geographic scale. Useful for sanity-
    checking whether the chosen center has any street network at all before
    paying for OSRM calls.
    """
    if not waypoints:
        raise ValueError("waypoints is empty")
    lats = [p[0] for p in waypoints]
    lons = [p[1] for p in waypoints]
    center = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)

    m = folium.Map(location=center, zoom_start=14, tiles="OpenStreetMap")
    folium.PolyLine(
        waypoints + [waypoints[0]],
        color="#d93025",
        weight=3,
        opacity=0.9,
        tooltip="Idealized outline (no street snap)",
    ).add_to(m)
    for i, (lat, lon) in enumerate(waypoints):
        folium.CircleMarker(
            location=(lat, lon),
            radius=2,
            color="#d93025",
            fill=True,
            fill_opacity=1.0,
            popup=f"point {i}",
        ).add_to(m)
    m.fit_bounds([(min(lats), min(lons)), (max(lats), max(lons))])
    m.get_root().html.add_child(folium.Element(f"<h3 style='padding:8px'>{title}</h3>"))
    m.save(out_path)
