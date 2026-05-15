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
import math
from dataclasses import dataclass, field

import numpy as np

from .centroid_project import centroid_project_contour
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
from .gpx_export import GpxMetadata, build_gpx, build_gpx_multi_segment
from .mapmatch import MatchedRoute, load_graph, map_match, map_match_dispatch
from .ocr import OcrResult, candidate_pixel_anchors, fetch_image, ocr_image


logger = logging.getLogger(__name__)


@dataclass
class Reconstruction:
    """Bundle of every intermediate + the final GPX (when confidence ≥ threshold).

    ``kind`` distinguishes:
      * ``"street"`` — full OCR-anchored affine reconstruction. Runnable GPX
        whose coordinates are believed correct to street-scale.
      * ``"city-scale"`` — Phase 4b centroid-anchored fallback for images with
        no OCR'd streets. Coordinates are an approximate placement around the
        title-derived city centroid; the *shape* is faithful but the actual
        streets it lands on are decorative, not the route the artist ran.

    ``review_status`` distinguishes:
      * ``"shipped"`` — confidence ≥ ``strict_threshold`` (default 0.6).
      * ``"review"`` — confidence in ``[min_confidence, strict_threshold)``;
        gate the iOS client behind a manual-approval flag.
      * ``None``     — below ``min_confidence``; no GPX written.
    """

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
    kind: str = "street"
    review_status: str | None = None
    failure: str | None = None     # short reason when confidence is below threshold
    diagnostics: dict = field(default_factory=dict)

    @property
    def is_runnable(self) -> bool:
        """True when the GPX coordinates are believed accurate to street-scale.

        City-scale fallbacks are decorative only — the iOS client should NOT
        offer these as a navigable route.
        """
        return self.kind == "street" and self.gpx_xml is not None


def _dedup_gcps_by_geo(
    gcps: list[GroundControlPoint],
    *,
    min_separation_m: float = 5.0,
) -> list[GroundControlPoint]:
    """Drop GCPs that resolve to (effectively) the same geographic point.

    Two OCR'd street labels that Nominatim's top-N hits both pin to the same
    way node count as *one* anchor — the affine is under-constrained by the
    duplicate. We keep the highest-weight (OCR confidence) hit from each
    geographic cluster, where two anchors are considered duplicates when
    their haversine separation is below ``min_separation_m``.

    Why ``5 m``: a typical OSM way node spacing is 10-50 m; two distinct
    streets meeting at one intersection have lat/lon offsets of at least one
    block (~80 m). Anything closer is almost certainly the same node hit by
    two slightly different OCR'd labels.
    """
    if len(gcps) < 2:
        return list(gcps)
    # Sort by weight desc so the best confidence wins each cluster.
    ordered = sorted(gcps, key=lambda g: -g.weight)
    kept: list[GroundControlPoint] = []
    for g in ordered:
        too_close = False
        for k in kept:
            # Approximate haversine with equirectangular at this latitude.
            dlat = (g.lat - k.lat) * 111_000.0
            cos_lat = max(math.cos(math.radians((g.lat + k.lat) / 2.0)), 1e-6)
            dlon = (g.lon - k.lon) * 111_000.0 * cos_lat
            if (dlat * dlat + dlon * dlon) ** 0.5 < min_separation_m:
                too_close = True
                break
        if not too_close:
            kept.append(g)
    return kept


def _gcp_pixel_hull_frac(
    gcps: list[GroundControlPoint],
    *,
    image_height: int,
    image_width: int,
) -> float:
    """Convex-hull area of the GCP pixel locations, as a fraction of image area.

    Catches two degenerate cases that an over-determined affine fit cannot
    detect from RMSE alone:

      * **Cluster:** all GCPs sit within a small image region (e.g. five OCR'd
        labels all on the same street block). The affine fit is well-determined
        *locally*, but extrapolating to far image pixels — which the contour
        spans — multiplies the geographic error by the inverse of the
        coverage fraction.
      * **Collinear:** all GCPs lie on (or near) a single line. The affine is
        under-determined perpendicular to that line; convex-hull area collapses
        to zero, exposing the degeneracy.

    The single-block case is the dominant failure mode in PoC run #2
    (e.g. London Bear: 5 GCPs, RMSE 0.0 m, but contour projection drifts
    wildly off the cartoon).
    """
    if len(gcps) < 3 or image_height <= 0 or image_width <= 0:
        return 0.0
    try:
        from shapely.geometry import MultiPoint
    except ImportError:
        # Fallback: bounding-box area (looser but still useful)
        xs = [g.x_px for g in gcps]
        ys = [g.y_px for g in gcps]
        bbox_area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        return bbox_area / (image_height * image_width)
    hull = MultiPoint([(g.x_px, g.y_px) for g in gcps]).convex_hull
    return float(hull.area) / float(image_height * image_width)


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


def _city_scale_fallback(
    rec: Reconstruction,
    *,
    title_latlon: tuple[float, float],
    title_confidence: float,
    target_width_m: float,
    gpx_metadata: GpxMetadata | None,
) -> Reconstruction:
    """Phase 4b: city-scale decorative reconstruction when no streets were OCR'd.

    Mutates ``rec`` in place and returns it. Marks ``kind="city-scale"``,
    sets confidence from the title geocoder (clamped to [0.1, 0.5]), and
    always tags ``review_status="review"`` — city-scale outputs are never
    runnable, so they never get the strict ``"shipped"`` tier.
    """
    assert rec.contour is not None    # caller already validated
    city_lat, city_lon = title_latlon
    # Use the full multi-polyline decomposition (Phase 4b) so the GPX captures
    # the whole cartoon — legs, ears, tail — not just the single longest
    # endpoint-to-endpoint path the legacy ``polyline`` field carries.
    source = rec.contour.polylines if rec.contour.polylines else rec.contour.polyline
    try:
        proj = centroid_project_contour(
            source,
            city_lat=city_lat,
            city_lon=city_lon,
            target_width_m=target_width_m,
        )
    except Exception as exc:                                     # noqa: BLE001
        rec.failure = f"city-scale: {exc!r}"
        return rec
    rec.geo_polyline = proj.polyline
    rec.kind = "city-scale"
    # Confidence reflects how much we trust the title geocoding, capped low
    # because the streets aren't really right — only the city is.
    rec.confidence = max(0.1, min(0.5, title_confidence))
    rec.review_status = "review"
    rec.failure = None
    rec.diagnostics["centroid_scale_m_per_px"] = proj.scale_m_per_pixel
    rec.diagnostics["centroid_bbox_width_m"] = proj.bbox_width_m
    rec.diagnostics["centroid_bbox_height_m"] = proj.bbox_height_m
    rec.diagnostics["centroid_n_segments"] = len(proj.polylines)
    # Multi-segment GPX track preserves branching shape; renderers break
    # between segments instead of drawing impossible connector lines.
    rec.gpx_xml = build_gpx_multi_segment(proj.polylines, metadata=gpx_metadata)
    return rec


def reconstruct(
    image_url: str,
    *,
    crossref_client,
    download_graph: bool = True,
    min_streets: int = 3,
    min_gcps: int = 5,
    min_gcp_hull_frac: float = 0.05,
    min_rmse_m: float = 0.5,
    cluster_radius_km: float = 3.0,
    min_confidence: float = 0.4,
    strict_threshold: float = 0.6,
    waypoint_step_m: float = 30.0,
    mapmatch_mode: str = "dijkstra",
    mapmatch_k_paths: int = 1,
    mapmatch_rerank: str = "shape",
    mapmatch_use_via_nodes: bool = False,
    hmm_obs_noise_m: float = 50.0,
    hmm_max_dist_m: float = 200.0,
    bbox_pad_m: float = 200.0,
    fidelity_buffer_m: float = 25.0,
    title_latlon: tuple[float, float] | None = None,
    title_confidence: float = 0.5,
    centroid_target_width_m: float = 4_000.0,
    gpx_metadata: GpxMetadata | None = None,
) -> Reconstruction:
    """Run the full image → GPX pipeline on one strav.art image.

    Returns a :class:`Reconstruction` even on failure; ``failure`` carries a
    short description of which stage gave up. Stages that succeed populate
    their respective fields, so the caller can introspect even partial runs
    for diagnostics.

    Gating knobs (raised by Phase 4b after the PoC found that ``min_streets=3``
    let degenerate fits through):

    * ``min_gcps``: minimum GCPs to attempt an affine fit (default 5).
      With 3 GCPs the affine is exactly determined → RMSE is trivially zero
      and tells you nothing about correctness. ≥5 is the smallest count
      where RMSE on real Nominatim-resolved anchors is a meaningful signal.
    * ``min_gcp_hull_frac``: minimum convex-hull area of GCP pixel locations
      as a fraction of image area (default 0.05). Rejects "5 anchors on one
      city block" — the fit looks great locally but contour projection drifts
      wildly when extrapolated to the rest of the image.
    * ``min_rmse_m``: minimum residual to accept (default 0.5 m). With ≥4
      over-determined anchors RMSE should always be > 0 on real data;
      RMSE < 0.5 m indicates near-collinear or duplicate GCPs (a degenerate
      fit that exactly matches its inputs but has unstable extrapolation).

    Confidence tiers:

    * ``confidence ≥ strict_threshold`` (default 0.6) → ``review_status="shipped"``
    * ``min_confidence ≤ confidence < strict_threshold`` → ``"review"``
      (GPX is still written; iOS client may filter)
    * ``confidence < min_confidence`` (default 0.4) → no GPX, ``review_status=None``

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
        # Phase 4b — if Phase 1's title geocoder placed this route in a city,
        # produce a decorative city-scale projection instead of giving up.
        # ``kind="city-scale"`` warns downstream consumers not to treat it as
        # a navigable GPX. With no title_latlon, the original failure stands.
        if title_latlon is not None:
            return _city_scale_fallback(
                rec,
                title_latlon=title_latlon,
                title_confidence=title_confidence,
                target_width_m=centroid_target_width_m,
                gpx_metadata=gpx_metadata,
            )
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
    raw_gcps = _gcps_from_ocr(rec.ocr, rec.crossref)
    gcps = _dedup_gcps_by_geo(raw_gcps)
    rec.diagnostics["n_gcps_raw"] = len(raw_gcps)
    rec.diagnostics["n_gcps"] = len(gcps)
    if len(gcps) < min_gcps:
        rec.failure = f"georef: only {len(gcps)} unique GCPs (need ≥{min_gcps})"
        return rec
    img_h, img_w = bgr.shape[:2]
    hull_frac = _gcp_pixel_hull_frac(gcps, image_height=img_h, image_width=img_w)
    rec.diagnostics["gcp_hull_frac"] = hull_frac
    if hull_frac < min_gcp_hull_frac:
        rec.failure = (
            f"georef: GCPs cover only {hull_frac:.1%} of image "
            f"(need ≥{min_gcp_hull_frac:.0%} — clustered/collinear anchors give degenerate fit)"
        )
        return rec
    try:
        rec.georectification = fit_affine(gcps)
    except Exception as exc:                                     # noqa: BLE001
        rec.failure = f"georef: {exc!r}"
        return rec
    # Anti-degeneracy check on the post-RANSAC fit:
    # 5 GCPs that all happen to fit one affine to <1m means either the OCR
    # found duplicate hits or the RANSAC inlier set collapsed to a near-
    # collinear cluster. Both produce extrapolation garbage.
    if (rec.georectification.n_anchors >= 4
            and rec.georectification.rmse_m < min_rmse_m):
        rec.failure = (
            f"georef: suspicious RMSE={rec.georectification.rmse_m:.2f} m "
            f"with {rec.georectification.n_anchors} GCPs "
            f"(< {min_rmse_m} m — degenerate fit)"
        )
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
    # Option 4: build via-node list from the GCPs that survived RANSAC.
    # Each inlier GCP is an OCR'd street whose Nominatim hit lat/lon we trust;
    # snap each to its nearest OSM graph node and pass into map_match as a
    # hard via-point. Dijkstra then routes THROUGH the OCR-identified
    # intersections in order — the cartoon's shape between them becomes a
    # tie-breaker, not the routing skeleton.
    via_nodes_arg: list[tuple[float, float, int]] | None = None
    if mapmatch_use_via_nodes and rec.georectification.kept_gcps:
        try:
            import osmnx as ox
            inlier_lats = [g.lat for g in rec.georectification.kept_gcps]
            inlier_lons = [g.lon for g in rec.georectification.kept_gcps]
            inlier_node_ids = ox.distance.nearest_nodes(graph, X=inlier_lons, Y=inlier_lats)
            via_nodes_arg = [
                (float(g.lat), float(g.lon), int(nid))
                for g, nid in zip(rec.georectification.kept_gcps, inlier_node_ids)
            ]
            rec.diagnostics["via_nodes_count"] = len(via_nodes_arg)
        except Exception as exc:                                  # noqa: BLE001
            logger.warning("via_nodes build failed: %r — falling back to no-via map_match", exc)
            via_nodes_arg = None

    try:
        rec.matched = map_match_dispatch(
            rec.geo_polyline, graph,
            mode=mapmatch_mode,
            waypoint_step_m=waypoint_step_m,
            k_shortest_paths=mapmatch_k_paths,
            rerank=mapmatch_rerank,
            via_nodes=via_nodes_arg,
            hmm_obs_noise_m=hmm_obs_noise_m,
            hmm_max_dist_m=hmm_max_dist_m,
        )
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
    rec.review_status = "shipped" if rec.confidence >= strict_threshold else "review"
    return rec
