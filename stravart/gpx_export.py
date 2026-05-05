"""Serialise a snapped (lat, lon) polyline to a GPX 1.1 document.

Wraps :mod:`gpxpy` so the consumer side (DoodleRun's iOS importer or any
GPX-aware running app) gets a standards-compliant XML blob with one
``<rte>`` element. We use ``rte`` (route) rather than ``trk`` (track)
because strav.art images describe a planned path, not a recorded one —
no per-point timestamps to invent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import gpxpy
import gpxpy.gpx


@dataclass(frozen=True)
class GpxMetadata:
    """Optional metadata tags written into the GPX document."""

    name: str = ""
    description: str = ""
    source: str = ""
    keywords: tuple[str, ...] = ()


def build_gpx(
    coords: list[tuple[float, float]],
    *,
    metadata: GpxMetadata | None = None,
) -> str:
    """Build a GPX 1.1 string with one route from ``coords``.

    The first/last point are NOT auto-deduped — pass already-snapped output
    from :mod:`stravart.mapmatch`. Points with NaN/inf are silently skipped
    so a partially failed map-match still produces a valid file.
    """
    gpx = gpxpy.gpx.GPX()
    gpx.creator = "stravart-finder Phase 3"
    if metadata:
        if metadata.name:
            gpx.name = metadata.name
        if metadata.description:
            gpx.description = metadata.description
        if metadata.keywords:
            gpx.keywords = ", ".join(metadata.keywords)

    route = gpxpy.gpx.GPXRoute()
    if metadata and metadata.name:
        route.name = metadata.name
    if metadata and metadata.description:
        route.description = metadata.description
    if metadata and metadata.source:
        route.source = metadata.source
    gpx.routes.append(route)

    for lat, lon in coords:
        if not (
            isinstance(lat, (int, float))
            and isinstance(lon, (int, float))
            and -90.0 <= lat <= 90.0
            and -180.0 <= lon <= 180.0
        ):
            continue
        route.points.append(gpxpy.gpx.GPXRoutePoint(latitude=float(lat), longitude=float(lon)))

    return gpx.to_xml()


def write_gpx(
    coords: list[tuple[float, float]],
    out_path: str | Path,
    *,
    metadata: GpxMetadata | None = None,
) -> Path:
    """Write the GPX to ``out_path`` (creating parent dirs). Returns the path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_gpx(coords, metadata=metadata))
    return out
