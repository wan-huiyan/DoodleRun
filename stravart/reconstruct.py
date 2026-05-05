"""End-to-end image-to-GPX orchestrator.

Wires the Phase 3 modules into a single ``reconstruct(image, ...)``
entry point used by the CLI and the batch driver:

    image bytes
      → contour.extract_route       (HSV mask → skeleton → polyline)
      → ocr.ocr_image               (street-name fragments + per-frag bboxes)
      → crossref.find_geocode       (Nominatim resolution; reused from Phase 2)
      → georef.fit_affine           (pixel → lat/lon GCPs from OCR anchors)
      → georef.project_polyline     (transform contour pixels to (lat, lon))
      → mapmatch.load_graph         (OSM walk graph for the projected bbox)
      → mapmatch.map_match          (Dijkstra-snap to streets)
      → fidelity_score.fidelity     (compare snapped vs. projected)
      → gpx_export.build_gpx        (GPX 1.1 string)

The orchestrator returns a :class:`Reconstruction` carrying every
intermediate plus a unified ``confidence`` (0..1) that aggregates:
    * # of GCPs that survived RANSAC,
    * the georectification RMSE,
    * mean OCR confidence on the streets we used,
    * the fidelity score after snapping.

Only reconstructions with ``confidence > min_confidence`` (default 0.6)
are considered "shippable" — they're the ones to write GPX for and
expose in any client.

Heavy stages are gated behind explicit booleans so tests can short-
circuit (e.g. the OSM graph download).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from .contour import RouteContour, extract_route
from .crossref import CrossRefResult, GeocodeCluster, find_geocode
from .fidelity_score import FidelityScore, fidelity
from .georef import (
    GroundControlPoint,
    Georectification,
    bbox_of_geocoords,
    fit_affine,
    project_polyline,
)
from .gpx_export import GpxMetadata, build_gpx
from .mapmatch import MatchedRoute, load_graph, map_match
from .ocr import OcrResult, candidate_pixel_anchors, fetch_image, ocr_image


logger = logging.getLogger(__name__)


@dataclass
class Reconstruction:
    """Bundle of every intermediate + the final GPX (when confidence ≥ threshold)."""

    image_url: str
    contour: RouteContour | None = None
    ocr: OcrResult | None = None
    crossref: CrossRefResult | None = None
    georectification: Georectification | None = None
    geo_polyline: list[tuple[float, float]] | None = None
    matched: MatchedRoute | None = None
    fidelity: FidelityScore | None = None
    gpx_xml: str | None = None
    confidence: float = 0.0
    failure: str | None = None     # short reason when confidence is below threshold
    diagnostics: dict = field(default_factory=dict)


def _gcps_from_ocr(
    ocr: OcrResult,
    crossref: CrossRefResult,
) -> list[GroundControlPoint]:
    """Build ground control points by joining OCR anchors with Nominatim hits.

    For each OCR'd street that found at least one Nominatim hit *inside the
    chosen geocode cluster's bbox*, take the cluster-internal hit closest to
    the cluster centroid as the geographic anchor and the OCR fragment
    bbox-center as the pixel anchor. We restrict to in-cluster hits because
    the cluster has already been validated as a co-locating consensus —
    anything outside it is probably a same-named street in another city.
    """
    if crossref.cluster is None:
        return []
    cluster = crossref.cluster
    s, n, w, e = cluster.bbox    # min_lat, max_lat, min_lon, max_lon

    pixel_anchors = candidate_pixel_anchors(ocr)
    if not pixel_anchors:
        return []

    gcps: list[GroundControlPoint] = []
    for cand, (px, py) in pixel_anchors:
        ways = crossref.matches.get(cand.normalized, [])
        if not ways:
            continue
        in_cluster = [
            w_ for w_ in ways
            if s <= w_.lat <= n and w <= w_.lon <= e
        ]
        if not in_cluster:
            continue
        # Pick the hit closest to the cluster centroid as the geo anchor.
        best = min(
            in_cluster,
            key=lambda w_: (w_.lat - cluster.lat) ** 2 + (w_.lon - cluster.lon) ** 2,
        )
        gcps.append(GroundControlPoint(
            x_px=px, y_px=py,
            lat=best.lat, lon=best.lon,
            label=cand.normalized,
            weight=cand.confidence,
        ))
    return gcps


def _confidence(
    *,
    n_gcps: int,
    rmse_m: float,
    mean_ocr_conf: float,
    fidelity_score: float,
) -> float:
    """Aggregate the per-stage signals into a single 0..1 confidence.

    The signals are roughly independent — one being good doesn't make
    another good — so multiplying penalises any single weak stage.

    Components:
        * ``anchor_term``: ramps from 0 at 3 GCPs to 1.0 at ≥6.
        * ``rmse_term``: 1.0 when RMSE ≤ 30 m (one street block);
                        0.0 when RMSE ≥ 200 m. Linear in between.
        * ``ocr_term``: mean OCR confidence on the GCP streets, [0, 1].
        * ``fidelity_term``: the snapped-vs-projected score.
    """
    anchor_term = max(0.0, min(1.0, (n_gcps - 3) / 3.0))
    if n_gcps >= 6:
        anchor_term = 1.0
    elif n_gcps < 3:
        anchor_term = 0.0
    rmse_term = max(0.0, min(1.0, 1.0 - (rmse_m - 30.0) / 170.0))
    ocr_term = max(0.0, min(1.0, mean_ocr_conf))
    fid_term = max(0.0, min(1.0, fidelity_score))
    # geometric mean — penalises weak stages without zeroing the score.
    parts = [anchor_term, rmse_term, ocr_term, fid_term]
    parts = [max(p, 0.05) for p in parts]
    geo_mean = float(np.exp(np.mean(np.log(parts))))
    return geo_mean


def reconstruct(
    image_url: str,
    *,
    crossref_client,
    download_graph: bool = True,
    min_streets: int = 3,
    cluster_radius_km: float = 3.0,
    min_confidence: float = 0.6,
    waypoint_step_m: float = 30.0,
    bbox_pad_m: float = 200.0,
    fidelity_buffer_m: float = 25.0,
    gpx_metadata: GpxMetadata | None = None,
) -> Reconstruction:
    """Run the full image → GPX pipeline on one strav.art image.

    Returns a :class:`Reconstruction` even on failure; ``failure`` carries a
    short description of which stage gave up. Stages that succeed populate
    their respective fields, so the caller can introspect even partial runs
    for diagnostics.

    ``download_graph=False`` skips the OSMnx Overpass call — useful for
    tests that pre-supply a graph via the lower-level :mod:`mapmatch` API.
    """
    rec = Reconstruction(image_url=image_url)

    # 1. Image fetch + contour ---------------------------------------------
    try:
        bgr = fetch_image(image_url)
    except Exception as exc:                                     # noqa: BLE001
        rec.failure = f"fetch: {exc!r}"
        return rec
    rec.contour = extract_route(bgr)
    if not rec.contour.polyline or len(rec.contour.polyline) < 10:
        rec.failure = "contour: empty or too short"
        return rec

    # 2. OCR ----------------------------------------------------------------
    try:
        rec.ocr = ocr_image(bgr)
    except Exception as exc:                                     # noqa: BLE001
        rec.failure = f"ocr: {exc!r}"
        return rec
    if not rec.ocr.street_candidates:
        rec.failure = "ocr: no street candidates"
        return rec

    # 3. Cross-reference (Phase 2 logic, reused) ---------------------------
    try:
        rec.crossref = find_geocode(
            rec.ocr.street_candidates,
            crossref_client,
            min_streets=min_streets,
            cluster_radius_km=cluster_radius_km,
        )
    except Exception as exc:                                     # noqa: BLE001
        rec.failure = f"crossref: {exc!r}"
        return rec
    if rec.crossref.cluster is None:
        rec.failure = "crossref: no consensus cluster"
        return rec

    # 4. GCPs + georectification --------------------------------------------
    gcps = _gcps_from_ocr(rec.ocr, rec.crossref)
    rec.diagnostics["n_gcps"] = len(gcps)
    if len(gcps) < 3:
        rec.failure = f"georef: only {len(gcps)} GCPs (need ≥3)"
        return rec
    try:
        rec.georectification = fit_affine(gcps)
    except Exception as exc:                                     # noqa: BLE001
        rec.failure = f"georef: {exc!r}"
        return rec

    # 5. Project the contour into geographic space -------------------------
    rec.geo_polyline = project_polyline(rec.georectification, rec.contour.polyline)
    if not rec.geo_polyline:
        rec.failure = "georef: empty geo polyline"
        return rec

    # 6. Map-match against the OSM walking network ------------------------
    if not download_graph:
        rec.failure = "mapmatch: skipped (download_graph=False)"
        return rec

    bbox = bbox_of_geocoords(rec.geo_polyline, pad_m=bbox_pad_m)
    try:
        graph = load_graph(bbox, network_type="walk")
    except Exception as exc:                                     # noqa: BLE001
        rec.failure = f"mapmatch: graph load: {exc!r}"
        return rec
    try:
        rec.matched = map_match(rec.geo_polyline, graph, waypoint_step_m=waypoint_step_m)
    except Exception as exc:                                     # noqa: BLE001
        rec.failure = f"mapmatch: {exc!r}"
        return rec
    if not rec.matched.coords:
        rec.failure = "mapmatch: empty result"
        return rec

    # 7. Fidelity scoring + confidence aggregation ------------------------
    rec.fidelity = fidelity(
        rec.matched.coords,
        rec.geo_polyline,
        buffer_m=fidelity_buffer_m,
    )
    mean_ocr_conf = (
        sum(g.weight for g in gcps) / len(gcps) if gcps else 0.0
    )
    rec.confidence = _confidence(
        n_gcps=rec.georectification.n_anchors,
        rmse_m=rec.georectification.rmse_m,
        mean_ocr_conf=mean_ocr_conf,
        fidelity_score=rec.fidelity.score,
    )
    rec.diagnostics["mean_ocr_conf"] = mean_ocr_conf

    if rec.confidence < min_confidence:
        rec.failure = (
            f"confidence: {rec.confidence:.2f} < {min_confidence:.2f}"
        )
        return rec

    # 8. GPX --------------------------------------------------------------
    rec.gpx_xml = build_gpx(rec.matched.coords, metadata=gpx_metadata)
    return rec
