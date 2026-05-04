"""Unit tests for cross-reference + clustering logic.

We stub OverpassClient with an in-memory fake — there's no network anywhere
in this test module, by design.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from stravart.crossref import (
    CrossRefResult,
    GeocodeCluster,
    NominatimStreetClient,
    OverpassClient,
    OverpassWay,
    _cluster_points,
    find_geocode,
    haversine_km,
)
from stravart.streets import StreetCandidate


# ---------------------------------------------------------------- helpers

class FakeClient:
    """In-memory drop-in for OverpassClient — controlled by ``responses``."""

    def __init__(self, responses: dict[str, list[OverpassWay]]) -> None:
        self.responses = {k.lower(): v for k, v in responses.items()}
        self.calls: list[str] = []

    def ways_named(self, name: str) -> list[OverpassWay]:
        self.calls.append(name)
        return list(self.responses.get(name.lower(), []))


# ---------------------------------------------------------------- haversine

class TestHaversine:
    def test_zero_distance(self) -> None:
        assert haversine_km(51.0, -0.1, 51.0, -0.1) == pytest.approx(0.0)

    def test_one_degree_latitude_is_111_km(self) -> None:
        d = haversine_km(0.0, 0.0, 1.0, 0.0)
        assert d == pytest.approx(111.19, abs=0.5)

    def test_known_st_albans_to_london(self) -> None:
        d = haversine_km(51.7521, -0.336, 51.5074, -0.1278)
        # straight-line ~33-34 km; loose bound is fine
        assert 30 < d < 40


# -------------------------------------------------------- single-link clustering

class TestClusterPoints:
    def test_empty(self) -> None:
        assert _cluster_points([], radius_km=1.0) == []

    def test_two_close_points_merge(self) -> None:
        pts = [(51.0, -0.1, "A"), (51.001, -0.1, "B")]
        clusters = _cluster_points(pts, radius_km=1.0)
        assert len(clusters) == 1 and len(clusters[0]) == 2

    def test_two_distant_points_split(self) -> None:
        pts = [(51.0, -0.1, "A"), (40.0, -3.7, "B")]   # London ↔ Madrid
        clusters = _cluster_points(pts, radius_km=10.0)
        assert len(clusters) == 2

    def test_chain_merges_via_single_link(self) -> None:
        # A---B---C where A-C is too far but A-B and B-C are not.
        pts = [
            (51.0, -0.10, "A"),
            (51.0, -0.105, "B"),       # ~350 m east of A
            (51.0, -0.110, "C"),       # ~350 m east of B
        ]
        clusters = _cluster_points(pts, radius_km=0.5)
        assert len(clusters) == 1 and len(clusters[0]) == 3


# -------------------------------------------------------------- find_geocode

def _candidate(name: str, conf: float = 0.9) -> StreetCandidate:
    return StreetCandidate(raw=name, normalized=name, suffix="road", confidence=conf)


class TestFindGeocode:
    def test_returns_none_when_only_one_street_matches(self) -> None:
        client = FakeClient({
            "Broomfield Road": [OverpassWay("Broomfield Road", 51.75, -0.34)],
        })
        result = find_geocode(
            [_candidate("Broomfield Road"), _candidate("Partridge Avenue")],
            client,                                                   # type: ignore[arg-type]
        )
        assert result.cluster is None
        # The query attempt itself happened for both — caller can decide what
        # to do with that diagnostic info.
        assert "Partridge Avenue" in result.queried

    def test_co_located_streets_form_cluster(self) -> None:
        # Both streets exist in St Albans (~51.75, -0.34). Each appears once.
        client = FakeClient({
            "Broomfield Road":  [OverpassWay("Broomfield Road",  51.751, -0.341)],
            "Partridge Avenue": [OverpassWay("Partridge Avenue", 51.752, -0.339)],
        })
        result = find_geocode(
            [_candidate("Broomfield Road", 0.9),
             _candidate("Partridge Avenue", 0.8)],
            client,                                                   # type: ignore[arg-type]
        )
        assert result.cluster is not None
        assert result.cluster.lat == pytest.approx(51.7515, abs=0.01)
        assert result.cluster.lon == pytest.approx(-0.340, abs=0.01)
        assert sorted(result.cluster.streets) == ["Broomfield Road", "Partridge Avenue"]
        assert 0.5 < result.cluster.confidence < 0.96

    def test_picks_cluster_with_more_distinct_streets(self) -> None:
        # "High Road" exists in 3 cities. "Church Lane" exists in 2 of them.
        # Only the ones where BOTH exist should win — and the one with more
        # ways should be ranked higher.
        client = FakeClient({
            "High Road":   [
                OverpassWay("High Road", 51.50, -0.10),    # London
                OverpassWay("High Road", 53.48, -2.24),    # Manchester
                OverpassWay("High Road", 55.95, -3.19),    # Edinburgh (alone)
            ],
            "Church Lane": [
                OverpassWay("Church Lane", 51.501, -0.099),   # London
                OverpassWay("Church Lane", 51.502, -0.101),   # London (2nd way)
                OverpassWay("Church Lane", 53.481, -2.239),   # Manchester
            ],
        })
        result = find_geocode(
            [_candidate("High Road"), _candidate("Church Lane")],
            client,                                                   # type: ignore[arg-type]
            cluster_radius_km=2.0,
        )
        assert result.cluster is not None
        assert result.cluster.lat == pytest.approx(51.50, abs=0.05)
        assert result.cluster.n_ways == 3   # 1 High Rd + 2 Church Ln in London
        # Edinburgh's lone High Rd must not pull anyone in, since Church Ln
        # doesn't co-locate there.
        assert all(c < 56 for c in [result.cluster.lat])

    def test_respects_max_lookups(self) -> None:
        client = FakeClient({})
        find_geocode(
            [_candidate(f"Street{i} Road", 0.9 - i * 0.05) for i in range(20)],
            client,                                                   # type: ignore[arg-type]
            max_lookups=3,
            typo_variants=0,    # isolate the original-candidate cap
        )
        assert client.calls == ["Street0 Road", "Street1 Road", "Street2 Road"]

    def test_typo_variants_widen_query_when_exact_misses(self) -> None:
        # Exact spelling doesn't match; the 'om → cm' variant does. We expect
        # find_geocode to pivot to the variant rather than give up.
        client = FakeClient({
            "Broomfield Road": [OverpassWay("Broomfield Road", 51.74, 0.46,
                                            city="Chelmsford", country="UK")],
            "Dixon Avenue":    [OverpassWay("Dixon Avenue", 51.74, 0.46,
                                            city="Chelmsford", country="UK")],
        })
        result = find_geocode(
            [_candidate("Brocmfield Road"), _candidate("Dixon Avenue")],
            client,                                                   # type: ignore[arg-type]
            typo_variants=4,
        )
        assert result.cluster is not None
        assert "Broomfield Road" in client.calls
        assert result.cluster.city == "Chelmsford"

    def test_min_streets_threshold(self) -> None:
        # Only one street name returns ways, so even with min_streets=1 we
        # need to treat it as too-thin evidence by default.
        client = FakeClient({
            "Broomfield Road": [OverpassWay("Broomfield Road", 51.75, -0.34)],
            "Partridge Avenue": [],     # explicit no-result
        })
        r1 = find_geocode(
            [_candidate("Broomfield Road"), _candidate("Partridge Avenue")],
            client,                                                   # type: ignore[arg-type]
            min_streets=2,
        )
        assert r1.cluster is None

        # Lowering the bar to 1 should let it through (test of the knob,
        # not a recommended setting).
        r2 = find_geocode(
            [_candidate("Broomfield Road"), _candidate("Partridge Avenue")],
            client,                                                   # type: ignore[arg-type]
            min_streets=1,
        )
        assert r2.cluster is not None
        assert r2.cluster.streets == ["Broomfield Road"]


# --------------------------------------------------------- OverpassClient cache

class TestOverpassClientCache:
    """We can't hit the live API from CI — but we *can* exercise the cache
    file format + negative-cache replay."""

    def test_negative_cache_replay(self, tmp_path: Path) -> None:
        cache = tmp_path / "overpass.json"
        client = OverpassClient(cache_path=cache, rate_limit_seconds=0.0)
        client._negatives.add("noplace road")
        client._save_cache()

        # Re-instantiate to force fresh load
        client2 = OverpassClient(cache_path=cache, rate_limit_seconds=0.0)
        # Calling ways_named for a negative-cached name should NOT touch the
        # network. We verify by using a dummy URL that would otherwise fail.
        client2._url = "http://127.0.0.1:1/never-listening"
        assert client2.ways_named("Noplace Road") == []

    def test_positive_cache_replay(self, tmp_path: Path) -> None:
        cache = tmp_path / "overpass.json"
        client = OverpassClient(cache_path=cache, rate_limit_seconds=0.0)
        client._cache["broomfield road"] = [
            {"name": "Broomfield Road", "lat": 51.75, "lon": -0.34}
        ]
        client._save_cache()

        client2 = OverpassClient(cache_path=cache, rate_limit_seconds=0.0)
        client2._url = "http://127.0.0.1:1/never-listening"
        ways = client2.ways_named("Broomfield Road")
        assert ways[0].name == "Broomfield Road"
        assert ways[0].lat == pytest.approx(51.75)


class TestNominatimStreetClientCache:
    """Same JSON cache shape as Overpass; verify that the city/country side-
    car fields round-trip and that negative cache replay short-circuits."""

    def test_positive_cache_with_city_country(self, tmp_path: Path) -> None:
        cache = tmp_path / "nom.json"
        client = NominatimStreetClient(cache_path=cache, rate_limit_seconds=0.0)
        client._cache["broomfield road"] = [
            {"name": "Broomfield Road", "lat": 51.75, "lon": -0.34,
             "city": "Chelmsford", "country": "United Kingdom"},
        ]
        client._save_cache()

        client2 = NominatimStreetClient(cache_path=cache, rate_limit_seconds=0.0)
        client2._url = "http://127.0.0.1:1/never-listening"
        ways = client2.ways_named("Broomfield Road")
        assert ways[0].city == "Chelmsford"
        assert ways[0].country == "United Kingdom"

    def test_negative_cache_replay(self, tmp_path: Path) -> None:
        cache = tmp_path / "nom.json"
        client = NominatimStreetClient(cache_path=cache, rate_limit_seconds=0.0)
        client._negatives.add("noplace road")
        client._save_cache()

        client2 = NominatimStreetClient(cache_path=cache, rate_limit_seconds=0.0)
        client2._url = "http://127.0.0.1:1/never-listening"
        assert client2.ways_named("Noplace Road") == []
