"""Nominatim (OSM) geocoder with on-disk cache and 1 req/sec rate limit.

The OSM Nominatim public instance allows ~1 query per second and requires a
descriptive User-Agent. We cache aggressively because we'll re-run the indexer
incrementally; cache lives in a JSON file next to the DB.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "DoodleRun/0.1 stravart-finder (https://github.com/laurawan/DoodleRun)"


def _macos_keychain_bundle() -> str | None:
    """Export macOS keychain CAs to a PEM file so httpx can verify TLS through
    a corporate inspection proxy (Netskope/Zscaler/Palo Alto). Mirrors the
    helper in ``prototype/osrm_client.py`` — kept inline so this package has
    no dependency on the prototype layout.

    Returns the PEM path, or None on non-macOS / failure.
    """
    if sys.platform != "darwin":
        return None
    cache = os.path.join(tempfile.gettempdir(), "doodlerun-stravart-ca.pem")
    if os.path.exists(cache) and os.path.getsize(cache) > 0:
        return cache
    keychains = [
        "/Library/Keychains/System.keychain",
        "/System/Library/Keychains/SystemRootCertificates.keychain",
        os.path.expanduser("~/Library/Keychains/login.keychain-db"),
    ]
    try:
        with open(cache, "wb") as fh:
            for kc in keychains:
                if not os.path.exists(kc):
                    continue
                res = subprocess.run(
                    ["security", "find-certificate", "-a", "-p", kc],
                    capture_output=True, check=False,
                )
                if res.returncode == 0 and res.stdout:
                    fh.write(res.stdout)
        return cache if os.path.getsize(cache) > 0 else None
    except OSError:
        return None


def _make_ssl_context() -> ssl.SSLContext | bool:
    """Build an SSL context that trusts the macOS keychain on darwin, otherwise
    falls back to httpx's default (certifi)."""
    bundle = _macos_keychain_bundle()
    if bundle:
        ctx = ssl.create_default_context(cafile=bundle)
        return ctx
    return True  # httpx default verification


@dataclass(frozen=True)
class GeoResult:
    lat: float
    lon: float
    display_name: str
    country: str | None
    raw_query: str


class _RateLimiter:
    """Block until at least `min_interval` seconds have passed since last call."""
    def __init__(self, min_interval: float) -> None:
        self._min = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self._last + self._min - now
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last = time.monotonic()


class Geocoder:
    """Synchronous geocoder. JSON file cache avoids re-querying known places.

    Design notes:
      * The cache key is the *normalized query string* — different inputs that
        resolve to the same place are deduped at the geocoder level by upstream
        callers (parse_title produces canonical city names already).
      * `negatives` keeps a record of queries that returned no results so we
        don't hammer Nominatim repeatedly.
      * Cache flushes on every successful or negative result so the long-running
        indexer can be killed and resumed safely.
    """

    def __init__(
        self,
        cache_path: str | Path,
        rate_limit_seconds: float = 1.0,
        timeout: float = 15.0,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._rate = _RateLimiter(rate_limit_seconds)
        self._timeout = timeout
        self._cache: dict[str, dict] = {}
        self._negatives: set[str] = set()
        self._verify = _make_ssl_context()
        self._load_cache()

    # ------------------------------------------------------------------ cache
    def _load_cache(self) -> None:
        if self.cache_path.exists():
            try:
                blob = json.loads(self.cache_path.read_text())
                self._cache = blob.get("hits", {})
                self._negatives = set(blob.get("negatives", []))
            except (json.JSONDecodeError, OSError):
                # corrupt cache — start fresh, don't crash the pipeline
                self._cache = {}
                self._negatives = set()

    def _save_cache(self) -> None:
        tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        tmp.write_text(json.dumps(
            {"hits": self._cache, "negatives": sorted(self._negatives)},
            indent=2,
        ))
        tmp.replace(self.cache_path)

    @staticmethod
    def _normalize(query: str) -> str:
        return " ".join(query.strip().lower().split())

    # ------------------------------------------------------------------- API
    def geocode(self, query: str, country: str | None = None) -> GeoResult | None:
        """Geocode a place string. Returns None if nothing found."""
        full = f"{query}, {country}" if country else query
        key = self._normalize(full)
        if not key:
            return None
        if key in self._negatives:
            return None
        cached = self._cache.get(key)
        if cached:
            return GeoResult(**cached)

        self._rate.wait()
        try:
            resp = httpx.get(
                NOMINATIM_URL,
                params={
                    "q": full,
                    "format": "json",
                    "limit": "1",
                    "addressdetails": "1",
                },
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
                timeout=self._timeout,
                verify=self._verify,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            # transient — don't poison the cache
            return None

        if not data:
            self._negatives.add(key)
            self._save_cache()
            return None

        hit = data[0]
        result = GeoResult(
            lat=float(hit["lat"]),
            lon=float(hit["lon"]),
            display_name=hit.get("display_name", full),
            country=(hit.get("address") or {}).get("country"),
            raw_query=full,
        )
        self._cache[key] = result.__dict__
        self._save_cache()
        return result
