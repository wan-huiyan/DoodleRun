"""Batch driver for image → GPX reconstruction.

Counterpart to :mod:`stravart.ocr_pipeline`. Reads geocoded routes from the
catalog DB, runs :func:`stravart.reconstruct.reconstruct` on each, and
writes successful GPX files to ``<db_dir>/gpx/<route_id>.gpx`` while
recording the per-row outcome in three columns added by Phase 3
(``gpx_path``, ``reconstruction_confidence``, ``reconstruction_attempted_at``,
``reconstruction_failure``).

Resumable: every attempt sets ``reconstruction_attempted_at`` so re-running
the batch picks up where it left off. ``--retry-attempted`` forces a
re-run on already-attempted rows (useful after a code fix).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .crossref import NominatimStreetClient, OverpassClient
from .db import (
    connect, count_geocoded, count_reconstructions, count_routes,
    routes_needing_reconstruction, transaction, update_reconstruction,
)
from .gpx_export import GpxMetadata
from .reconstruct import Reconstruction, reconstruct


logger = logging.getLogger(__name__)


@dataclass
class ReconstructionOutcome:
    """One row's result. Surfaced for CLI reporting + tests."""

    route_id: int
    title: str
    image_url: str
    confidence: float
    failure: str | None
    gpx_path: str | None
    n_gcps: int
    fidelity_score: float | None
    kind: str = "street"
    review_status: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _gpx_dir(db_path: Path) -> Path:
    return db_path.parent / "gpx"


def _gpx_filename(route_id: int) -> str:
    return f"route_{route_id:05d}.gpx"


def _outcome_from(rec: Reconstruction, *, route_id: int, title: str,
                  gpx_relpath: str | None) -> ReconstructionOutcome:
    return ReconstructionOutcome(
        route_id=route_id,
        title=title,
        image_url=rec.image_url,
        confidence=rec.confidence,
        failure=rec.failure,
        gpx_path=gpx_relpath,
        n_gcps=int(rec.diagnostics.get("n_gcps", 0)),
        fidelity_score=rec.fidelity.score if rec.fidelity is not None else None,
        kind=rec.kind,
        review_status=rec.review_status,
    )


def run_batch(
    db_path: str | Path,
    *,
    crossref_cache: str | Path | None = None,
    crossref_backend: str = "nominatim",
    only_categories: list[str] | None = None,
    limit: int | None = None,
    retry_attempted: bool = False,
    min_confidence: float = 0.4,
    strict_threshold: float = 0.6,
    min_gcps: int = 5,
    waypoint_step_m: float = 30.0,
    mapmatch_k_paths: int = 1,
    mapmatch_rerank: str = "shape",
    mapmatch_use_via_nodes: bool = True,
    enable_city_scale_fallback: bool = True,
    progress_every: int = 5,
) -> list[ReconstructionOutcome]:
    """Drive Phase 3 reconstruction across the catalog. Returns per-row outcomes."""
    db_path = Path(db_path)
    cache = Path(crossref_cache) if crossref_cache else \
        db_path.parent / f"{crossref_backend}_cache.json"
    if crossref_backend == "overpass":
        crossref_client = OverpassClient(cache_path=cache)
    else:
        crossref_client = NominatimStreetClient(cache_path=cache)

    gpx_dir = _gpx_dir(db_path)
    gpx_dir.mkdir(parents=True, exist_ok=True)

    conn = connect(db_path)
    try:
        rows = routes_needing_reconstruction(
            conn,
            only_categories=only_categories,
            retry_attempted=retry_attempted,
            limit=limit,
        )
        logger.info(
            "reconstruct: %d candidates (db=%s, total=%d, geocoded=%d)",
            len(rows), db_path, count_routes(conn), count_geocoded(conn),
        )

        outcomes: list[ReconstructionOutcome] = []
        for i, row in enumerate(rows, start=1):
            # Pass title-derived lat/lon into the orchestrator so Phase 4b's
            # centroid fallback fires when OCR finds no street labels.
            title_latlon = None
            if enable_city_scale_fallback and row["lat"] is not None and row["lon"] is not None:
                title_latlon = (float(row["lat"]), float(row["lon"]))
            title_conf = float(row["geocode_confidence"] or 0.5)
            try:
                rec = reconstruct(
                    row["image_url"],
                    crossref_client=crossref_client,
                    download_graph=True,
                    min_confidence=min_confidence,
                    strict_threshold=strict_threshold,
                    min_gcps=min_gcps,
                    waypoint_step_m=waypoint_step_m,
                    mapmatch_k_paths=mapmatch_k_paths,
                    mapmatch_rerank=mapmatch_rerank,
                    mapmatch_use_via_nodes=mapmatch_use_via_nodes,
                    title_latlon=title_latlon,
                    title_confidence=title_conf,
                    gpx_metadata=GpxMetadata(
                        name=row["title"],
                        description=f"strav.art reconstruction (route {row['id']})",
                        source="stravart-finder Phase 4b",
                        keywords=("strav.art", row["category"]),
                    ),
                )
            except Exception as exc:                              # noqa: BLE001
                # Defensive — reconstruct() should already swallow most stage
                # errors into rec.failure. This catches truly unexpected ones
                # (e.g. an OOM during graph download) and lets the batch keep
                # going on the next row.
                rec = Reconstruction(
                    image_url=row["image_url"],
                    failure=f"orchestrator: {exc!r}",
                )

            gpx_relpath: str | None = None
            # Write GPX when reconstruct() emitted one. The orchestrator
            # already applied min_confidence for street-scale outputs;
            # city-scale fallbacks ship regardless of confidence because they
            # are the *only* signal we have for OCR-zero images and their
            # confidence is capped at 0.5 by design.
            should_write = rec.gpx_xml is not None and (
                rec.kind == "city-scale" or rec.confidence >= min_confidence
            )
            if should_write:
                out_path = gpx_dir / _gpx_filename(row["id"])
                out_path.write_text(rec.gpx_xml)
                # Store the path relative to the DB's parent so the catalog
                # remains relocatable.
                gpx_relpath = str(Path("gpx") / _gpx_filename(row["id"]))

            outcome = _outcome_from(
                rec, route_id=row["id"], title=row["title"],
                gpx_relpath=gpx_relpath,
            )
            outcomes.append(outcome)

            with transaction(conn):
                update_reconstruction(
                    conn, row["id"],
                    gpx_path=gpx_relpath,
                    confidence=rec.confidence,
                    attempted_at=_now(),
                    failure=rec.failure,
                    kind=rec.kind if gpx_relpath else None,
                    review_status=rec.review_status,
                )

            if i % progress_every == 0 or i == len(rows):
                ok = sum(1 for o in outcomes if o.gpx_path is not None)
                logger.info(
                    "  [%d/%d] shipped=%d (last: %s — %s; conf=%.2f)",
                    i, len(rows), ok, row["title"],
                    "OK" if outcome.gpx_path else (rec.failure or "?"),
                    rec.confidence,
                )
        return outcomes
    finally:
        conn.close()


def summary(outcomes: list[ReconstructionOutcome]) -> dict:
    """Compact stats with Phase 4b kind / review breakdown."""
    if not outcomes:
        return {"attempted": 0, "shipped": 0}
    with_gpx = [o for o in outcomes if o.gpx_path is not None]
    failures: dict[str, int] = {}
    for o in outcomes:
        if o.gpx_path is None:
            tag = (o.failure or "unknown").split(":", 1)[0]
            failures[tag] = failures.get(tag, 0) + 1
    return {
        "attempted": len(outcomes),
        "shipped":   len(with_gpx),
        "ship_rate": round(len(with_gpx) / len(outcomes), 3) if outcomes else 0.0,
        "by_kind": {
            "street":     sum(1 for o in with_gpx if o.kind == "street"),
            "city-scale": sum(1 for o in with_gpx if o.kind == "city-scale"),
        },
        "by_review_status": {
            "shipped": sum(1 for o in with_gpx if o.review_status == "shipped"),
            "review":  sum(1 for o in with_gpx if o.review_status == "review"),
        },
        "failure_modes": dict(sorted(failures.items(), key=lambda kv: -kv[1])),
        "mean_confidence": round(
            sum(o.confidence for o in outcomes) / len(outcomes), 3,
        ),
    }


def db_stats(db_path: str | Path) -> dict:
    conn = connect(db_path)
    try:
        return {
            "total":            count_routes(conn),
            "geocoded":         count_geocoded(conn),
            "reconstructions":  count_reconstructions(conn),
        }
    finally:
        conn.close()
