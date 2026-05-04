"""Batch OCR-geocode pipeline.

Reads ``routes WHERE lat IS NULL``, OCRs the image, queries Overpass to find
where the OCR'd street names co-locate, and writes the result back to the DB.
Idempotent: each row is marked ``ocr_attempted_at`` even on failure so the
batch can resume after Ctrl-C without redoing work.

Run via:
    python -m stravart.cli ocr-geocode --db data/stravart.sqlite --limit 50
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .crossref import CrossRefResult, OverpassClient, find_geocode
from .db import connect, count_by_geocode_source, count_geocoded, count_routes, \
    routes_needing_ocr, transaction, update_ocr_geocode
from .ocr import OcrResult, fetch_image, ocr_image


logger = logging.getLogger(__name__)


@dataclass
class OcrGeocodeOutcome:
    """Per-route result. Exposed for tests + CLI reporting."""

    route_id: int
    title: str
    image_url: str
    fragments: int                       # raw OCR fragments
    candidates: int                      # street candidates after filtering
    matched: int                         # how many had Overpass hits
    cluster_lat: float | None = None
    cluster_lon: float | None = None
    cluster_streets: list[str] | None = None
    confidence: float = 0.0
    error: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def process_one(
    image_url: str,
    overpass: OverpassClient,
    *,
    languages: tuple[str, ...] = ("en",),
    min_streets: int = 2,
    cluster_radius_km: float = 3.0,
    inpaint: bool = True,
) -> tuple[OcrResult | None, CrossRefResult | None, str | None]:
    """OCR + cross-reference one image. Returns ``(ocr, xref, error)``.

    Errors are returned as strings rather than raised so the batch can swallow
    transient image-fetch / Overpass failures.
    """
    try:
        bgr = fetch_image(image_url)
    except Exception as exc:                                # noqa: BLE001
        return None, None, f"fetch: {exc!r}"
    try:
        ocr = ocr_image(bgr, languages=languages, inpaint=inpaint)
    except Exception as exc:                                # noqa: BLE001
        return None, None, f"ocr: {exc!r}"
    if not ocr.street_candidates:
        return ocr, None, None
    try:
        xref = find_geocode(
            ocr.street_candidates,
            overpass,
            min_streets=min_streets,
            cluster_radius_km=cluster_radius_km,
        )
    except Exception as exc:                                # noqa: BLE001
        return ocr, None, f"overpass: {exc!r}"
    return ocr, xref, None


def run_batch(
    db_path: str | Path,
    *,
    overpass_cache: str | Path | None = None,
    languages: tuple[str, ...] = ("en",),
    only_categories: list[str] | None = None,
    limit: int | None = None,
    retry_attempted: bool = False,
    min_streets: int = 2,
    cluster_radius_km: float = 3.0,
    progress_every: int = 5,
) -> list[OcrGeocodeOutcome]:
    """Drive OCR geocoding across the catalog. Returns per-route outcomes."""
    db_path = Path(db_path)
    cache = Path(overpass_cache) if overpass_cache else \
        db_path.parent / "overpass_cache.json"
    overpass = OverpassClient(cache_path=cache)

    conn = connect(db_path)
    try:
        rows = routes_needing_ocr(
            conn,
            only_categories=only_categories,
            retry_attempted=retry_attempted,
            limit=limit,
        )
        logger.info(
            "ocr-geocode: %d candidates (db=%s, total=%d, geocoded=%d)",
            len(rows), db_path, count_routes(conn), count_geocoded(conn),
        )

        outcomes: list[OcrGeocodeOutcome] = []
        for i, row in enumerate(rows, start=1):
            ocr, xref, err = process_one(
                row["image_url"], overpass,
                languages=languages,
                min_streets=min_streets,
                cluster_radius_km=cluster_radius_km,
            )
            outcome = OcrGeocodeOutcome(
                route_id=row["id"],
                title=row["title"],
                image_url=row["image_url"],
                fragments=len(ocr.fragments) if ocr else 0,
                candidates=len(ocr.street_candidates) if ocr else 0,
                matched=len({k for k, v in (xref.matches.items() if xref else []) if v}),
                error=err,
            )

            streets_json = json.dumps(
                [c.normalized for c in (ocr.street_candidates if ocr else [])],
                ensure_ascii=False,
            )
            attempted_at = _now()

            cluster = xref.cluster if xref else None
            with transaction(conn):
                if cluster:
                    outcome.cluster_lat = cluster.lat
                    outcome.cluster_lon = cluster.lon
                    outcome.cluster_streets = cluster.streets
                    outcome.confidence = cluster.confidence
                    update_ocr_geocode(
                        conn, row["id"],
                        lat=cluster.lat, lon=cluster.lon,
                        confidence=cluster.confidence,
                        streets_json=streets_json,
                        attempted_at=attempted_at,
                    )
                else:
                    update_ocr_geocode(
                        conn, row["id"],
                        lat=None, lon=None,
                        confidence=0.0,
                        streets_json=streets_json,
                        attempted_at=attempted_at,
                    )

            outcomes.append(outcome)
            if i % progress_every == 0 or i == len(rows):
                hits = sum(1 for o in outcomes if o.cluster_lat is not None)
                logger.info(
                    "  [%d/%d] hits=%d (last: %s — %s)",
                    i, len(rows), hits, row["title"],
                    "OK" if cluster else (err or "no-cluster"),
                )
        return outcomes
    finally:
        conn.close()


def summary(outcomes: list[OcrGeocodeOutcome]) -> dict:
    """Compact stats for logging or CLI output."""
    if not outcomes:
        return {"attempted": 0, "geocoded": 0, "success_rate": 0.0}
    geocoded = sum(1 for o in outcomes if o.cluster_lat is not None)
    return {
        "attempted":   len(outcomes),
        "geocoded":    geocoded,
        "success_rate": round(geocoded / len(outcomes), 3),
        "errors":      sum(1 for o in outcomes if o.error),
        "no_streets":  sum(1 for o in outcomes if o.candidates == 0 and o.error is None),
        "no_cluster":  sum(
            1 for o in outcomes
            if o.candidates > 0 and o.cluster_lat is None and o.error is None
        ),
    }


def db_stats(db_path: str | Path) -> dict:
    conn = connect(db_path)
    try:
        return {
            "total":            count_routes(conn),
            "geocoded":         count_geocoded(conn),
            "by_source":        count_by_geocode_source(conn),
        }
    finally:
        conn.close()
