"""Pydantic request/response models for the DoodleRun API."""

from __future__ import annotations

from typing import List, Tuple

from pydantic import BaseModel, Field


class ShapeMeta(BaseModel):
    """Metadata about a single available animal shape."""
    id: str = Field(..., examples=["pig"])
    name: str = Field(..., examples=["Pig"])
    emoji: str = Field(..., examples=["🐷"])
    distinctive_features: str = Field(
        ...,
        examples=["curly tail, ear bump, two wide legs"],
    )


class ShapesResponse(BaseModel):
    shapes: List[ShapeMeta]


class GenerateRequest(BaseModel):
    shape: str = Field(..., examples=["pig"])
    lat: float = Field(..., ge=-90, le=90, examples=[51.75])
    lon: float = Field(..., ge=-180, le=180, examples=[-0.34])
    distance_km: float = Field(..., gt=0, le=50, examples=[10.0])
    waypoints: int = Field(40, ge=10, le=80,
                           description="Resampled waypoint count sent to OSRM")
    iterations: int = Field(5, ge=1, le=10,
                            description="Rescaling passes to hit target distance "
                                        "(only when search_radius_km is omitted)")
    search_radius_km: float | None = Field(
        None, gt=0, le=200,
        description="If set, enable fidelity-first search: try multiple candidate "
                    "centers within this radius and pick the one that traces the "
                    "shape most accurately. Distance becomes a hint, not a target.",
    )
    candidates: int = Field(5, ge=1, le=15,
                            description="With search_radius_km set, number of candidate centers")
    scales: int = Field(3, ge=1, le=8,
                        description="With search_radius_km set, number of scale candidates per center")


class GeoJSONLineString(BaseModel):
    """GeoJSON LineString — coordinates are [lon, lat] pairs (note the order)."""
    type: str = Field(default="LineString", frozen=True)
    coordinates: List[Tuple[float, float]]


class GenerateResponse(BaseModel):
    shape: str
    target_distance_m: float
    routed_distance_m: float
    error_pct: float = Field(
        ...,
        description="(routed - target) / target × 100",
    )
    geojson: GeoJSONLineString = Field(
        ...,
        description="Snapped street-level polyline for map display",
    )
    waypoints: List[Tuple[float, float]] = Field(
        ...,
        description="Idealized outline waypoints (lat, lon) before street snapping",
    )
    gpx: str = Field(..., description="GPX 1.1 document as a string")
    kml: str = Field(..., description="KML 2.2 document — uploadable to Google My Maps")
    fidelity: float = Field(
        ...,
        description="Shape fidelity score (lower = better, 0 = perfect tracing). "
                    "Mean nearest-neighbor distance between snapped route and "
                    "idealized outline, normalised by the shape's bbox diagonal.",
    )
    chosen_lat: float = Field(..., description="Final route center lat (may differ "
                                                "from request lat when search is on)")
    chosen_lon: float = Field(..., description="Final route center lon")


class PreviewRequest(BaseModel):
    """Render the idealized outline at a given center+distance, no OSRM call.

    Used by the SPA to show a doodle preview before the user commits to a
    full /generate (which is slow + rate-limited)."""
    shape: str = Field(..., examples=["pig"])
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    distance_km: float = Field(..., gt=0, le=50,
                               description="Sets scale via the same heuristic "
                                           "the router uses to seed its grid")


class PreviewResponse(BaseModel):
    shape: str
    scale_m_per_unit: float
    center_lat: float
    center_lon: float
    waypoints: List[Tuple[float, float]] = Field(
        ..., description="Idealized outline in (lat, lon)",
    )
    geojson: GeoJSONLineString = Field(
        ..., description="Same outline as a GeoJSON LineString for map drawing",
    )


class ShareRequest(BaseModel):
    """Caller may either pass a previously-generated route inline OR pass
    the same fields as /generate to have the server compute one and store it.
    Inline is preferred — avoids a second OSRM call when the iOS app already
    holds a result.
    """
    shape: str
    geojson: GeoJSONLineString
    waypoints: List[Tuple[float, float]]
    routed_distance_m: float


class ShareResponse(BaseModel):
    id: str = Field(..., description="Opaque share id")
    viewer_url: str = Field(..., description="Path on this server that renders the route in a Leaflet viewer (mobile-friendly)")
    json_url: str = Field(..., description="Path that returns the raw route as JSON for the viewer to fetch")
    expires_in_seconds: int


class HealthResponse(BaseModel):
    status: str = "ok"
    shapes_loaded: int
