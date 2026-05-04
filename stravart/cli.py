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
from .pipeline import index_jsonl, stats
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
