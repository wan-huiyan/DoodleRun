"""Cross-reference OCR'd street names against OpenStreetMap.

If we have ≥2 distinct street names from one strav.art image and the same
two names appear within a small bounding box somewhere on Earth, we've
geocoded the route. Implementation:

  1. For each candidate, query Nominatim for places named ``<street>`` —
     returns up to 40 results worldwide, each with lat/lon + city + country.
  2. Cluster the union of all returned points by spatial proximity. A cluster
     is valid when it contains ways from ≥``min_streets`` distinct candidates.
  3. Rank clusters by (#distinct streets, total OCR confidence). The winning
     cluster's centroid is our geocode; its bbox spans the route area.

Why not Overpass? An unbounded planet-wide ``way["highway"]["name"="X"]`` query
OOMs the public Overpass instance (>2 GB RAM) on common names like
"High Street". Nominatim's index is purpose-built for this lookup pattern
and bounds results by importance.

The legacy ``OverpassClient`` class is kept as an opt-in alternative for
callers that want planet-wide ways with raw OSM tags — it's still useful
for testing and for very-rare names where Nominatim's importance ranking
hides the right hit.
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

from .streets import StreetCandidate, name_variants


logger = logging.getLogger(__name__)


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
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
    """One way (or Nominatim hit) that matched a street-name query.

    The class is named for the original Overpass-based design but is now also
    populated by ``NominatimStreetClient`` so the clustering layer doesn't
    care which backend produced the points.
    """

    name: str
    lat: float
    lon: float
    city: str | None = None
    country: str | None = None


@dataclass
class GeocodeCluster:
    """Spatial cluster of ways that satisfies the multi-street constraint."""

    lat: float
    lon: float
    bbox: tuple[float, float, float, float]   # min_lat, max_lat, min_lon, max_lon
    streets: list[str]                        # *normalized* names that hit
    n_ways: int                               # total ways in the cluster
    confidence: float                         # 0..1 derived from #streets + spread
    city: str | None = None
    country: str | None = None


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


# ----------------- Nominatim street-search client (default backend) ----------

class NominatimStreetClient:
    """Default backend: Nominatim full-text search keyed on street name.

    Each ``ways_named(name)`` call hits ``/search?q=<name>&limit=40`` and
    returns up to 40 worldwide hits as ``OverpassWay`` (the name predates the
    backend swap; kept for interface compatibility).

    Public-instance limits: 1 req/sec + descriptive User-Agent. We honour both.
    The on-disk cache is the same JSON-blob shape as ``OverpassClient``.
    """

    def __init__(
        self,
        cache_path: str | Path,
        *,
        rate_limit_seconds: float = 1.1,    # 1 req/sec public-instance limit
        timeout: float = 30.0,
        url: str = NOMINATIM_URL,
        limit: int = 40,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._rate = _RateLimiter(rate_limit_seconds)
        self._timeout = timeout
        self._verify = _make_ssl_context()
        self._url = url
        self._limit = limit
        self._cache: dict[str, list[dict]] = {}
        self._negatives: set[str] = set()
        self._load_cache()

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

    def _query(self, params: dict, cache_key: str) -> list[OverpassWay]:
        """Shared cached request body for ways_named / ways_named_in."""
        if cache_key in self._negatives:
            return []
        cached = self._cache.get(cache_key)
        if cached is not None:
            return [OverpassWay(**w) for w in cached]

        self._rate.wait()
        try:
            resp = httpx.get(
                self._url,
                params={
                    **params,
                    "format": "json",
                    "limit": str(self._limit),
                    "addressdetails": "1",
                    "dedupe": "0",
                },
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
                timeout=self._timeout,
                verify=self._verify,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("nominatim error %r for %r — skipping", exc, cache_key)
            return []

        ways: list[OverpassWay] = []
        for hit in data:
            try:
                lat = float(hit["lat"])
                lon = float(hit["lon"])
            except (KeyError, ValueError):
                continue
            addr = hit.get("address") or {}
            city = (
                addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("suburb")
                or addr.get("municipality")
            )
            country = addr.get("country")
            ways.append(OverpassWay(
                name=hit.get("display_name", "").split(",", 1)[0],
                lat=lat, lon=lon, city=city, country=country,
            ))

        if ways:
            self._cache[cache_key] = [w.__dict__ for w in ways]
        else:
            self._negatives.add(cache_key)
        self._save_cache()
        return ways

    def ways_named(self, name: str) -> list[OverpassWay]:
        """Worldwide top-N hits for a street name."""
        key = name.strip().lower()
        return self._query({"q": name}, cache_key=key)

    def ways_named_in(
        self, name: str, city: str, country: str | None = None,
    ) -> list[OverpassWay]:
        """Structured-search verification: does ``<name>`` exist in ``<city>``?

        Used by the two-pass cross-reference algorithm to confirm whether
        a candidate street appears in a city we've already seen via another
        candidate. This is necessary because Nominatim's worldwide top-40
        is importance-biased and frequently hides the right city.
        """
        key = f"in::{city.lower()}::{(country or '').lower()}::{name.strip().lower()}"
        params: dict[str, str] = {"street": name, "city": city}
        if country:
            params["country"] = country
        return self._query(params, cache_key=key)


# ---------------- Clustering --------------------------------------------------

_EARTH_R_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_R_KM * math.asin(min(1.0, math.sqrt(a)))


def _cluster_points(
    items: list,
    *,
    radius_km: float,
) -> list[list]:
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


def _two_pass_verify(
    candidates: list[StreetCandidate],
    client,
    matches: dict[str, list[OverpassWay]],
    queried: list[str],
    confidence_lookup: dict[str, float],
    min_streets: int,
) -> GeocodeCluster | None:
    """Recover a hit when the worldwide-top-40 single-pass missed the city.

    Builds a list of (city, country) hypotheses from any candidate that did
    return hits, then asks Nominatim — via ``ways_named_in`` — whether each
    other candidate also exists in that city. Wins the hypothesis where the
    most distinct candidates verify. Skipped silently if the client doesn't
    expose ``ways_named_in`` (i.e. OverpassClient).
    """
    if not hasattr(client, "ways_named_in"):
        return None

    # Hypothesis = (city, country). Frequency-weighted by how many of the
    # candidate streets had ANY hit there in the worldwide pass.
    hyp_counts: dict[tuple[str, str], int] = {}
    for ways in matches.values():
        seen_in_this_candidate: set[tuple[str, str]] = set()
        for w in ways:
            if w.city and w.country:
                seen_in_this_candidate.add((w.city, w.country))
        for h in seen_in_this_candidate:
            hyp_counts[h] = hyp_counts.get(h, 0) + 1

    if not hyp_counts:
        return None

    # Sort hypotheses: those that already have ≥min_streets hits jump first
    # (cheap structural confirm), then by frequency descending.
    ordered = sorted(hyp_counts.items(), key=lambda kv: -kv[1])

    best: tuple[GeocodeCluster, int] | None = None
    for (city, country), _ in ordered[:25]:    # cap to keep API quota sane
        verified_streets: list[OverpassWay] = []
        verified_names: set[str] = set()
        for cand in candidates:
            # Already confirmed via worldwide pass? Use that hit.
            already = [
                w for w in matches.get(cand.normalized, [])
                if w.city == city and w.country == country
            ]
            if already:
                verified_streets.extend(already)
                verified_names.add(cand.normalized)
                continue
            # Otherwise structurally check this street in the hypothesised city.
            try:
                hits = client.ways_named_in(cand.normalized, city, country)
            except Exception:                                    # noqa: BLE001
                hits = []
            queried.append(f"{cand.normalized} @ {city}")
            if hits:
                # Filter to confirm city actually matches (Nominatim sometimes
                # returns nearby substitutes).
                hits = [h for h in hits if h.city == city]
            if hits:
                verified_streets.extend(hits)
                verified_names.add(cand.normalized)

        if len(verified_names) < min_streets:
            continue

        lats = [w.lat for w in verified_streets]
        lons = [w.lon for w in verified_streets]
        bbox = (min(lats), max(lats), min(lons), max(lons))
        clat = sum(lats) / len(lats)
        clon = sum(lons) / len(lons)
        conf_sum = sum(confidence_lookup.get(n, 0.0) for n in verified_names)
        score = min(0.95,
                    0.4 + 0.15 * len(verified_names)
                    + 0.4 * (conf_sum / max(len(verified_names), 1)))
        cluster = GeocodeCluster(
            lat=clat, lon=clon, bbox=bbox,
            streets=sorted(verified_names),
            n_ways=len(verified_streets),
            confidence=score,
            city=city, country=country,
        )
        if best is None or len(verified_names) > best[1]:
            best = (cluster, len(verified_names))

    return best[0] if best else None


def find_geocode(
    candidates: list[StreetCandidate],
    client,
    *,
    min_streets: int = 2,
    cluster_radius_km: float = 3.0,
    max_lookups: int = 6,
    typo_variants: int = 3,
    two_pass: bool = True,
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
        # Fallback: try OCR-typo variants when the exact spelling drew a blank.
        # Variants can recover Brocmfield → Broomfield, Partrdge → Partridge.
        if not ways and typo_variants > 0:
            for variant in name_variants(cand.normalized,
                                         max_variants=typo_variants):
                if variant == cand.normalized:
                    continue
                ways = client.ways_named(variant)
                if ways:
                    queried.append(variant)
                    break
        if ways:
            matches[cand.normalized] = ways

    if len({k for k, v in matches.items() if v}) < min_streets:
        return CrossRefResult(cluster=None, matches=matches, queried=queried)

    # Flatten with a label for distinct-name accounting; carry city/country
    # so the winning cluster can self-describe without re-querying.
    points: list[tuple[float, float, str, str | None, str | None]] = []
    for street_name, ways in matches.items():
        for w in ways:
            points.append((w.lat, w.lon, street_name, w.city, w.country))

    # Cluster on (lat, lon) but keep the full tuple in the cluster lists.
    coord_only = [(p[0], p[1], p[2]) for p in points]
    coord_clusters = _cluster_points(coord_only, radius_km=cluster_radius_km)
    # Reattach the city/country sidecars by index.
    point_lookup = {(p[0], p[1], p[2]): p for p in points}
    clusters = [
        [point_lookup[(c[0], c[1], c[2])] for c in cluster]
        for cluster in coord_clusters
    ]

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
        # City / country: most-common non-null among cluster members.
        cities = [p[3] for p in cluster if p[3]]
        countries = [p[4] for p in cluster if p[4]]
        city = max(set(cities), key=cities.count) if cities else None
        country = max(set(countries), key=countries.count) if countries else None
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
            city=city,
            country=country,
        )
        # Sort key: more distinct streets > higher OCR-conf > more ways
        sort_key = (-len(names), -conf_sum, -len(cluster))
        scored.append((gc, sort_key))

    if scored:
        scored.sort(key=lambda x: x[1])
        return CrossRefResult(cluster=scored[0][0], matches=matches, queried=queried)

    if two_pass:
        cluster = _two_pass_verify(
            candidates, client, matches, queried,
            confidence_lookup, min_streets,
        )
        if cluster is not None:
            return CrossRefResult(cluster=cluster, matches=matches, queried=queried)

    return CrossRefResult(cluster=None, matches=matches, queried=queried)
