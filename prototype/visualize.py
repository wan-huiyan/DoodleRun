"""Render a generated route as an interactive Folium HTML map.

Two layers:
- Blue line: the OSRM-snapped street-level polyline (what the runner actually runs).
- Red dashed line + markers: the idealized pig outline waypoints before snapping,
  so you can see how much the streets distorted the shape.
"""

from __future__ import annotations

from typing import List, Tuple

import folium


def render(
    polyline: List[Tuple[float, float]],
    waypoints: List[Tuple[float, float]],
    out_path: str,
    title: str = "GPS Art Route",
) -> None:
    if not polyline:
        raise ValueError("polyline is empty")

    lats = [p[0] for p in polyline]
    lons = [p[1] for p in polyline]
    center = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)

    m = folium.Map(location=center, zoom_start=15, tiles="OpenStreetMap")

    folium.PolyLine(
        polyline,
        color="#1a73e8",
        weight=5,
        opacity=0.85,
        tooltip="Snapped run route",
    ).add_to(m)

    folium.PolyLine(
        waypoints,
        color="#d93025",
        weight=2,
        opacity=0.7,
        dash_array="6,8",
        tooltip="Idealized pig outline",
    ).add_to(m)

    for i, (lat, lon) in enumerate(waypoints):
        folium.CircleMarker(
            location=(lat, lon),
            radius=3,
            color="#d93025",
            fill=True,
            fill_opacity=1.0,
            popup=f"waypoint {i}",
        ).add_to(m)

    folium.Marker(polyline[0], icon=folium.Icon(color="green"), tooltip="Start").add_to(m)
    folium.Marker(polyline[-1], icon=folium.Icon(color="red"), tooltip="Finish").add_to(m)

    m.fit_bounds([(min(lats), min(lons)), (max(lats), max(lons))])
    m.get_root().html.add_child(folium.Element(f"<h3 style='padding:8px'>{title}</h3>"))
    m.save(out_path)
