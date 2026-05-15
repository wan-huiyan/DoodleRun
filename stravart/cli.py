"""CLI for the strav.art finder pipeline.

Examples:
    python -m stravart.cli scrape --out data/raw.jsonl
    python -m stravart.cli scrape --categories cats-dogs birds --out data/raw.jsonl
    python -m stravart.cli index --jsonl data/raw.jsonl --db data/stravart.sqlite
    python -m stravart.cli stats --db data/stravart.sqlite
    python -m stravart.cli search --db data/stravart.sqlite \
        --lat 51.7521 --lon -0.336 --radius 30 --query dog
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .db import connect
from .ocr_pipeline import db_stats as ocr_db_stats
from .ocr_pipeline import run_batch as ocr_run_batch
from .ocr_pipeline import summary as ocr_summary
from .pipeline import index_jsonl, stats
from .reconstruct_pipeline import db_stats as reconstruct_db_stats
from .reconstruct_pipeline import run_batch as reconstruct_run_batch
from .reconstruct_pipeline import summary as reconstruct_summary
from .scrape import scrape_all
from .search import search_as_dicts
from .synonyms import CATEGORIES


def _add_scrape(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("scrape", help="Scrape strav.art galleries to a JSONL file")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--categories", nargs="+", default=list(CATEGORIES))
    p.add_argument("--headed", action="store_true", help="Show browser (debug)")
    p.add_argument("--limit-per-category", type=int, default=None)


def _add_index(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("index", help="Geocode + index a scraped JSONL into SQLite")
    p.add_argument("--jsonl", type=Path, required=True)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--geocode-cache", type=Path, default=None)
    p.add_argument("--skip-geocoding", action="store_true")


def _add_stats(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("stats", help="Print catalog stats")
    p.add_argument("--db", type=Path, required=True)


def _add_ocr_geocode(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "ocr-geocode",
        help="OCR strav.art images and geocode via OSM street co-location",
    )
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--crossref-cache", type=Path, default=None,
                   help="Path to JSON cache for street-name lookups")
    p.add_argument("--crossref-backend", choices=["nominatim", "overpass"],
                   default="nominatim",
                   help="OSM backend (nominatim=default, recommended)")
    p.add_argument("--languages", nargs="+", default=["en"],
                   help="EasyOCR language codes, e.g. en de fr")
    p.add_argument("--categories", nargs="+", default=None,
                   help="Restrict to these category slugs")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--retry-attempted", action="store_true",
                   help="Re-run OCR on rows that previously failed")
    p.add_argument("--min-streets", type=int, default=2,
                   help="Distinct OCR street names required for a cluster hit")
    p.add_argument("--cluster-radius-km", type=float, default=3.0)


def _add_ocr_stats(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("ocr-stats", help="Print geocode-source breakdown")
    p.add_argument("--db", type=Path, required=True)


def _add_reconstruct(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "reconstruct",
        help="Phase 3: turn geocoded routes into GPX via image → contour → "
             "georef → map-match",
    )
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--crossref-cache", type=Path, default=None,
                   help="Path to JSON cache for street-name lookups (shared "
                        "with ocr-geocode)")
    p.add_argument("--crossref-backend", choices=["nominatim", "overpass"],
                   default="nominatim")
    p.add_argument("--categories", nargs="+", default=None,
                   help="Restrict to these category slugs")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--retry-attempted", action="store_true",
                   help="Re-run reconstruction on rows that previously failed")
    p.add_argument("--min-confidence", type=float, default=0.4,
                   help="Below this, no GPX is written. Default 0.4 puts the "
                        "0.4-0.6 band into the review tier; raise to 0.6 to "
                        "ship only strict-tier reconstructions.")
    p.add_argument("--strict-threshold", type=float, default=0.6,
                   help="Confidence ≥ this stamps review_status='shipped'; "
                        "lower than this within [min-confidence, strict) "
                        "stamps 'review'.")
    p.add_argument("--min-gcps", type=int, default=5,
                   help="Minimum unique GCPs to attempt an affine fit. "
                        "Phase 4b raised this from 3 → 5 (3-GCP fits are "
                        "exactly determined and produce no honest residual).")
    p.add_argument("--no-city-scale-fallback", action="store_true",
                   help="Disable the Phase 4b centroid-anchored fallback. "
                        "Routes without OCR'd streets become failures.")
    p.add_argument("--waypoint-step-m", type=float, default=30.0,
                   help="Spacing between map-match waypoints (metres).")
    p.add_argument("--mapmatch-k-paths", type=int, default=1,
                   help="Top-K candidate paths per segment for shape-aware "
                        "rerank. Default 1 (legacy Dijkstra). Set >1 to "
                        "experiment with k-shortest-paths + Fréchet rerank "
                        "— note this only helps when the OSM graph offers "
                        "multiple comparable routes between waypoints, which "
                        "is rare on dense city street networks.")
    p.add_argument("--mapmatch-rerank", choices=["shape", "length"],
                   default="shape",
                   help="Pick best of K paths by 'shape' (Fréchet vs cartoon) "
                        "or 'length' (legacy — shortest by edge length).")
    p.add_argument("--via-nodes", action="store_true",
                   help="Enable Phase 4b option 4 (OCR anchors as Dijkstra "
                        "via-points). OFF by default — empirical sweep on "
                        "#584 elephant + #53 Regent's Park showed fidelity "
                        "DROPPED because Nominatim's street-centroid pins "
                        "force detours away from the cartoon's actual "
                        "crossing point. Kept opt-in for future "
                        "per-street-node refinement.")
    p.add_argument("--mapmatch-mode", choices=["dijkstra", "hmm"],
                   default="dijkstra",
                   help="Phase 4c: pick the map-matcher. 'dijkstra' is the "
                        "legacy Phase 3 per-segment shortest-path snap. 'hmm' "
                        "is a Hidden Markov Model (Newson-Krumm via "
                        "leuvenmapmatching) that scores entire path "
                        "likelihoods against the observed shape — fixes "
                        "global wrong-turn failures that local Dijkstra "
                        "can't recover from.")
    p.add_argument("--hmm-obs-noise-m", type=float, default=50.0,
                   help="Standard deviation of observation noise for HMM mode. "
                        "Default 50m for cartoon-projection use; raise to "
                        "100-150m for noisier projections.")
    p.add_argument("--hmm-max-dist-m", type=float, default=200.0,
                   help="HMM hard cutoff: candidate edges must lie within "
                        "this many metres of each observation.")


def _add_reconstruct_stats(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "reconstruct-stats",
        help="Print reconstruction attempt / ship counts",
    )
    p.add_argument("--db", type=Path, required=True)


def _add_search(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("search", help="Local query against the catalog")
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--radius", type=float, default=30.0, help="km")
    p.add_argument("--query", type=str, default=None)
    p.add_argument("--limit", type=int, default=20)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    parser = argparse.ArgumentParser(prog="stravart")
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_scrape(sub)
    _add_index(sub)
    _add_stats(sub)
    _add_search(sub)
    _add_ocr_geocode(sub)
    _add_ocr_stats(sub)
    _add_reconstruct(sub)
    _add_reconstruct_stats(sub)
    args = parser.parse_args(argv)

    if args.cmd == "scrape":
        total = asyncio.run(scrape_all(
            out_jsonl=args.out,
            categories=args.categories,
            headless=not args.headed,
            limit_per_category=args.limit_per_category,
        ))
        print(f"scraped {total} items -> {args.out}")
        return 0

    if args.cmd == "index":
        n, g = index_jsonl(
            jsonl_path=args.jsonl,
            db_path=args.db,
            geocode_cache_path=args.geocode_cache,
            skip_geocoding=args.skip_geocoding,
        )
        print(f"indexed {n} rows ({g} geocoded) -> {args.db}")
        return 0

    if args.cmd == "stats":
        print(json.dumps(stats(args.db), indent=2))
        return 0

    if args.cmd == "ocr-geocode":
        outcomes = ocr_run_batch(
            db_path=args.db,
            crossref_cache=args.crossref_cache,
            crossref_backend=args.crossref_backend,
            languages=tuple(args.languages),
            only_categories=args.categories,
            limit=args.limit,
            retry_attempted=args.retry_attempted,
            min_streets=args.min_streets,
            cluster_radius_km=args.cluster_radius_km,
        )
        print(json.dumps(ocr_summary(outcomes), indent=2))
        return 0

    if args.cmd == "ocr-stats":
        print(json.dumps(ocr_db_stats(args.db), indent=2))
        return 0

    if args.cmd == "reconstruct":
        outcomes = reconstruct_run_batch(
            db_path=args.db,
            crossref_cache=args.crossref_cache,
            crossref_backend=args.crossref_backend,
            only_categories=args.categories,
            limit=args.limit,
            retry_attempted=args.retry_attempted,
            min_confidence=args.min_confidence,
            strict_threshold=args.strict_threshold,
            min_gcps=args.min_gcps,
            waypoint_step_m=args.waypoint_step_m,
            mapmatch_mode=args.mapmatch_mode,
            mapmatch_k_paths=args.mapmatch_k_paths,
            mapmatch_rerank=args.mapmatch_rerank,
            mapmatch_use_via_nodes=args.via_nodes,
            hmm_obs_noise_m=args.hmm_obs_noise_m,
            hmm_max_dist_m=args.hmm_max_dist_m,
            enable_city_scale_fallback=not args.no_city_scale_fallback,
        )
        print(json.dumps(reconstruct_summary(outcomes), indent=2))
        return 0

    if args.cmd == "reconstruct-stats":
        print(json.dumps(reconstruct_db_stats(args.db), indent=2))
        return 0

    if args.cmd == "search":
        conn = connect(args.db)
        try:
            hits = search_as_dicts(
                conn, args.lat, args.lon, args.radius, args.query, args.limit,
            )
        finally:
            conn.close()
        print(json.dumps(hits, indent=2, default=str))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
