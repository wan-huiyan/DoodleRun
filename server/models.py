"""Pydantic request/response models for the DoodleRun API."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field


# Phase 5: v2_multi is the new default. The legacy generator stays callable
# behind algorithm="legacy" for a transition window.
Algorithm = Literal["legacy", "v2_multi"]


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
    distance_km: float = Field(..., gt=0, le=50, examples=[20.0])
    algorithm: Algorithm = Field(
        "v2_multi",
        description="Route generator. 'v2_multi' is the Phase 3 OSMnx + W-K + "
                    "Optuna multi-variant pipeline (default). 'legacy' is the "
                    "Phase 1 OSRM iterate-on-scale generator, kept for fallback.",
    )
    # ---- legacy-only knobs (ignored when algorithm == "v2_multi") -------
    waypoints: int = Field(40, ge=10, le=80,
                           description="Resampled waypoint count sent to OSRM (legacy)")
    iterations: int = Field(5, ge=1, le=10,
                            description="Rescaling passes (legacy, search_radius_km omitted)")
    search_radius_km: float | None = Field(
        None, gt=0, le=200,
        description="Legacy fidelity-first search radius (legacy only).",
    )
    candidates: int = Field(5, ge=1, le=15, description="Legacy: candidate centers")
    scales: int = Field(3, ge=1, le=8, description="Legacy: scale candidates per center")
    # ---- v2-only knobs --------------------------------------------------
    n_trials: int = Field(
        30, ge=5, le=200,
        description="v2: Optuna TPE trials per outline variant. 30 is the smoke default.",
    )
    timeout_s_per_variant: float = Field(
        60.0, gt=0, le=600.0,
        description="v2: wall-clock budget per variant in seconds.",
    )
    max_variants: int = Field(
        2, ge=1, le=5,
        description="v2: how many outline variants (canonical + Quick Draw) to try.",
    )


class GeoJSONLineString(BaseModel):
    """GeoJSON LineString — coordinates are [lon, lat] pairs (note the order)."""
    type: str = Field(default="LineString", frozen=True)
    coordinates: List[Tuple[float, float]]


class ScoreBreakdown(BaseModel):
    """Per-metric fidelity contributions; matches the prototype's combined_score
    breakdown. Lower is better; weights sum to 1.0."""
    hausdorff: float
    frechet: float
    area_iou: float
    turning: float
    weights: Dict[str, float]


class GenerateResponse(BaseModel):
    shape: str
    algorithm: Algorithm = Field(
        "legacy",
        description="Which generator produced this route.",
    )
    target_distance_m: float
    routed_distance_m: float
    distance_m: float = Field(
        ...,
        description="Alias of routed_distance_m for clients that prefer the "
                    "canonical Phase-5 field name.",
    )
    error_pct: float = Field(
        ...,
        description="(routed - target) / target × 100",
    )
    geojson: GeoJSONLineString = Field(
        ...,
        description="Snapped street-level polyline for map display",
    )
    polyline: List[Tuple[float, float]] = Field(
        ...,
        description="Snapped street-level polyline as (lat, lon) pairs. "
                    "Same data as geojson.coordinates, in [lat, lon] order.",
    )
    waypoints: List[Tuple[float, float]] = Field(
        ...,
        description="Idealized outline waypoints (lat, lon) before street snapping",
    )
    gpx: str = Field(..., description="GPX 1.1 document as a string")
    kml: str = Field(..., description="KML 2.2 document — uploadable to Google My Maps")
    fidelity: float = Field(
        ...,
        description="Phase-1 fidelity score (mean nearest-neighbor deviation, "
                    "lower = better). Kept for back-compat with legacy clients.",
    )
    score: float = Field(
        ...,
        description="Distance-adjusted fidelity score (lower = better). For "
                    "v2_multi this is the Optuna best; for legacy it equals "
                    "`fidelity`.",
    )
    score_breakdown: Optional[ScoreBreakdown] = Field(
        None,
        description="Per-metric breakdown (v2_multi only).",
    )
    variant_index: Optional[int] = Field(
        None,
        description="Which outline variant won the search (v2_multi only). "
                    "0 = canonical hand-drawn outline; 1+ = Quick Draw exemplars.",
    )
    best_params: Optional[Dict[str, Any]] = Field(
        None,
        description="Winning (offset_lat, offset_lon, scale_factor, rotation_deg, "
                    "variant_index) tuple from the Optuna search (v2_multi only).",
    )
    chosen_lat: float = Field(..., description="Final route center lat (may differ "
                                                "from request lat when search is on)")
    chosen_lon: float = Field(..., description="Final route center lon")


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
