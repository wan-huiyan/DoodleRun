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
                            description="Rescaling passes to hit target distance")


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
