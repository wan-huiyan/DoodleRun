"""Cross-reference OCR'd street names against OpenStreetMap.

If we have ≥2 distinct street names from one strav.art image and the same
two names appear within a small bounding box somewhere on Earth, we've
geocoded the route. Implementation:

  1. For each candidate, query Overpass for ways tagged ``highway=*`` whose
     ``name`` (or ``name:*`` localised tag) matches the OCR'd string.
  2. Collect (lat, lon, name) per matched way (Overpass ``out center;``).
  3. Cluster the union of all matches by spatial proximity. A cluster is
     valid when it contains ways from ≥``min_streets`` distinct candidates.
  4. Rank clusters by (#distinct streets, total OCR confidence). The winning
     cluster's centroid is our geocode; its bbox spans the route area.

Overpass quirks we care about:
  * The public ``overpass-api.de`` instance accepts ~5 calls per minute and
    returns 429 + ``Retry-After`` when overloaded — we honour that header.
  * Some endpoints return a ``remark`` field instead of an HTTP error when
    the query times out; we treat any ``remark`` containing "timed out" or
    "out of memory" as a transient failure and retry once after backoff.
  * Names are case-sensitive in the regex form. We use ``"name"~"^X$",i`` to
    sidestep that.
"""

from __future__ import annotations

import json
import logging
import math
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import httpx

from .streets import StreetCandidate


logger = logging.getLogger(__name__)


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "DoodleRun/0.2 stravart-finder (https://github.com/laurawan/DoodleRun)"


# --- TLS through corporate proxies (mirrors stravart.geocode) -------------

def _macos_keychain_bundle() -> str | None:
    if sys.platform != "darwin":
        return None
    cache = os.path.join(tempfile.gettempdir(), "doodlerun-stravart-overpass-ca.pem")
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
    bundle = _macos_keychain_bundle()
    if bundle:
        return ssl.create_default_context(cafile=bundle)
    return True


# ---------------- Overpass client with rate-limit + cache -----------------

class _RateLimiter:
    """Wall-clock min interval between calls. Thread-safe."""

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


@dataclass
class OverpassWay:
    """One way that matched the name query."""

    name: str
    lat: float
    lon: float


@dataclass
class GeocodeCluster:
    """Spatial cluster of ways that satisfies the multi-street constraint."""

    lat: float
    lon: float
    bbox: tuple[float, float, float, float]   # min_lat, max_lat, min_lon, max_lon
    streets: list[str]                        # *normalized* names that hit
    n_ways: int                               # total ways in the cluster
    confidence: float                         # 0..1 derived from #streets + spread


@dataclass
class CrossRefResult:
    """Outcome of one cross-reference attempt."""

    cluster: GeocodeCluster | None
    matches: dict[str, list[OverpassWay]] = field(default_factory=dict)
    queried: list[str] = field(default_factory=list)


class OverpassClient:
    """Minimal Overpass client with on-disk JSON cache + 1 req/12s rate limit.

    The cache is keyed on the *canonical* street name passed to ``ways_named``;
    that's what makes batch runs cheap on the 100th re-attempt.
    """

    def __init__(
        self,
        cache_path: str | Path,
        *,
        rate_limit_seconds: float = 12.0,   # ~5 req/min headroom
        timeout: float = 90.0,
        url: str = OVERPASS_URL,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._rate = _RateLimiter(rate_limit_seconds)
        self._timeout = timeout
        self._verify = _make_ssl_context()
        self._url = url
        self._cache: dict[str, list[dict]] = {}
        self._negatives: set[str] = set()
        self._load_cache()

    # ------------------------------------------------------------- cache
    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            blob = json.loads(self.cache_path.read_text())
            self._cache = blob.get("hits", {})
            self._negatives = set(blob.get("negatives", []))
        except (OSError, json.JSONDecodeError):
            self._cache = {}
            self._negatives = set()

    def _save_cache(self) -> None:
        tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        tmp.write_text(json.dumps(
            {"hits": self._cache, "negatives": sorted(self._negatives)},
            indent=2,
        ))
        tmp.replace(self.cache_path)

    # ------------------------------------------------------- raw Overpass
    @staticmethod
    def _build_query(name: str) -> str:
        # Match name OR name:* localised; Overpass regex must escape backslashes,
        # but we only allow alphanumerics + spaces + a few punctuation chars
        # since `name` was already normalised by streets.parse_street.
        safe = name.replace("\\", "").replace('"', "")
        return (
            "[out:json][timeout:60];"
            "("
            f'  way["highway"]["name"~"^{safe}$",i];'
            f'  way["highway"]["name:en"~"^{safe}$",i];'
            ");"
            "out center 200;"
        )

    def ways_named(self, name: str) -> list[OverpassWay]:
        """Return up to 200 ``highway=*`` ways with this name worldwide.

        Returns ``[]`` for cache-negative names. Network failures raise.
        """
        key = name.strip().lower()
        if key in self._negatives:
            return []
        cached = self._cache.get(key)
        if cached is not None:
            return [OverpassWay(**w) for w in cached]

        query = self._build_query(name)
        for attempt in (1, 2):
            self._rate.wait()
            try:
                resp = httpx.post(
                    self._url,
                    data={"data": query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=self._timeout,
                    verify=self._verify,
                )
            except httpx.HTTPError as exc:
                if attempt == 1:
                    logger.warning("overpass transport error %r — backing off", exc)
                    time.sleep(20.0)
                    continue
                raise
            if resp.status_code == 429 or resp.status_code == 504:
                wait = float(resp.headers.get("Retry-After", "30"))
                logger.warning("overpass %s — sleeping %.0fs", resp.status_code, wait)
                time.sleep(wait)
                continue
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                if attempt == 1:
                    time.sleep(20.0)
                    continue
                raise
            try:
                data = resp.json()
            except ValueError:
                if attempt == 1:
                    time.sleep(20.0)
                    continue
                raise
            remark = data.get("remark", "")
            if remark and any(t in remark.lower() for t in ("timed out", "out of memory")):
                if attempt == 1:
                    logger.warning("overpass remark %r — retrying", remark)
                    time.sleep(20.0)
                    continue
            break
        else:
            return []

        ways: list[OverpassWay] = []
        for el in data.get("elements", []):
            if el.get("type") != "way":
                continue
            tags = el.get("tags", {})
            n = tags.get("name") or tags.get("name:en") or name
            center = el.get("center") or {}
            lat = center.get("lat")
            lon = center.get("lon")
            if lat is None or lon is None:
                continue
            ways.append(OverpassWay(name=n, lat=float(lat), lon=float(lon)))

        if ways:
            self._cache[key] = [w.__dict__ for w in ways]
        else:
            self._negatives.add(key)
        self._save_cache()
        return ways


# ---------------- Clustering --------------------------------------------------

_EARTH_R_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_R_KM * math.asin(min(1.0, math.sqrt(a)))


def _cluster_points(
    items: list[tuple[float, float, str]],
    *,
    radius_km: float,
) -> list[list[tuple[float, float, str]]]:
    """Greedy single-link clustering by haversine radius.

    items: ``(lat, lon, label)``. Returns clusters; each cluster is a list of
    the original items. We sort by latitude first to make the loop deterministic.
    """
    if not items:
        return []
    remaining = sorted(items, key=lambda x: (x[0], x[1]))
    clusters: list[list[tuple[float, float, str]]] = []
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        # Iteratively absorb nearby points (single-link)
        changed = True
        while changed:
            changed = False
            keep: list[tuple[float, float, str]] = []
            for p in remaining:
                if any(haversine_km(p[0], p[1], q[0], q[1]) <= radius_km for q in cluster):
                    cluster.append(p)
                    changed = True
                else:
                    keep.append(p)
            remaining = keep
        clusters.append(cluster)
    return clusters


def find_geocode(
    candidates: list[StreetCandidate],
    client: OverpassClient,
    *,
    min_streets: int = 2,
    cluster_radius_km: float = 3.0,
    max_lookups: int = 6,
) -> CrossRefResult:
    """Resolve a set of OCR candidates to a single (lat, lon) cluster.

    Algorithm:
      * Look up at most ``max_lookups`` candidates (highest-confidence first).
        We bound this so a cooked OCR pass with 30 fragments doesn't blow up
        Overpass quota.
      * Cluster all returned ways by ``cluster_radius_km``.
      * Drop clusters with fewer than ``min_streets`` *distinct* OCR'd names.
      * Rank survivors by (#distinct streets desc, sum of OCR confidence desc,
        total ways desc). Return the winner.
    """
    matches: dict[str, list[OverpassWay]] = {}
    queried: list[str] = []
    for cand in candidates[:max_lookups]:
        queried.append(cand.normalized)
        ways = client.ways_named(cand.normalized)
        if ways:
            matches[cand.normalized] = ways

    if len({k for k, v in matches.items() if v}) < min_streets:
        return CrossRefResult(cluster=None, matches=matches, queried=queried)

    # Flatten with a label for distinct-name accounting.
    points: list[tuple[float, float, str]] = []
    for street_name, ways in matches.items():
        for w in ways:
            points.append((w.lat, w.lon, street_name))

    clusters = _cluster_points(points, radius_km=cluster_radius_km)
    confidence_lookup = {c.normalized: c.confidence for c in candidates}

    scored: list[tuple[GeocodeCluster, tuple]] = []
    for cluster in clusters:
        names = {p[2] for p in cluster}
        if len(names) < min_streets:
            continue
        lats = [p[0] for p in cluster]
        lons = [p[1] for p in cluster]
        bbox = (min(lats), max(lats), min(lons), max(lons))
        # Centroid: mean lat/lon (good enough at city scale).
        clat = sum(lats) / len(lats)
        clon = sum(lons) / len(lons)
        conf_sum = sum(confidence_lookup.get(n, 0.0) for n in names)
        # 0..1 confidence: scale by how many distinct streets we matched and
        # by the average OCR confidence. Cap at 0.95 — never claim certainty
        # the title parser couldn't, which is the only "ground truth" path.
        score = min(0.95, 0.4 + 0.15 * len(names) + 0.4 * (conf_sum / max(len(names), 1)))
        gc = GeocodeCluster(
            lat=clat,
            lon=clon,
            bbox=bbox,
            streets=sorted(names),
            n_ways=len(cluster),
            confidence=score,
        )
        # Sort key: more distinct streets > higher OCR-conf > more ways
        sort_key = (-len(names), -conf_sum, -len(cluster))
        scored.append((gc, sort_key))

    if not scored:
        return CrossRefResult(cluster=None, matches=matches, queried=queried)

    scored.sort(key=lambda x: x[1])
    return CrossRefResult(cluster=scored[0][0], matches=matches, queried=queried)
