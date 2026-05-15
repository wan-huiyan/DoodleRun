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


def build_gpx_multi_segment(
    segments: list[list[tuple[float, float]]],
    *,
    metadata: GpxMetadata | None = None,
) -> str:
    """Build a GPX 1.1 string with one ``<trk>`` containing N ``<trkseg>``.

    Use when the source geometry has multiple disjoint segments (Phase 4b's
    city-scale fallback, where a cartoon dog yields 7+ polylines for legs/
    ears/tail). GPX consumers render each ``<trkseg>`` as its own connected
    line with breaks between — preserving the cartoon's branching shape.

    NaN/inf and out-of-range points are skipped silently. Segments that
    end up with <2 valid points are dropped.
    """
    gpx = gpxpy.gpx.GPX()
    gpx.creator = "stravart-finder Phase 4b"
    if metadata:
        if metadata.name:
            gpx.name = metadata.name
        if metadata.description:
            gpx.description = metadata.description
        if metadata.keywords:
            gpx.keywords = ", ".join(metadata.keywords)

    track = gpxpy.gpx.GPXTrack()
    if metadata and metadata.name:
        track.name = metadata.name
    if metadata and metadata.description:
        track.description = metadata.description
    if metadata and metadata.source:
        track.source = metadata.source
    gpx.tracks.append(track)

    for seg in segments:
        if not seg:
            continue
        track_seg = gpxpy.gpx.GPXTrackSegment()
        for lat, lon in seg:
            if not (
                isinstance(lat, (int, float))
                and isinstance(lon, (int, float))
                and -90.0 <= lat <= 90.0
                and -180.0 <= lon <= 180.0
            ):
                continue
            track_seg.points.append(
                gpxpy.gpx.GPXTrackPoint(latitude=float(lat), longitude=float(lon))
            )
        if len(track_seg.points) >= 2:
            track.segments.append(track_seg)

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
