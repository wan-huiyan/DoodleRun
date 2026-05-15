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
    PerStreetNodeClient,
    StreetNode,
    _cluster_points,
    find_geocode,
    haversine_km,
    pick_via_node_for_street,
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


class FakeNominatimClient(FakeClient):
    """FakeClient that also exposes ``ways_named_in`` so two-pass-verify runs.

    ``city_responses`` is keyed on (lower(name), city, country) so we can
    set up scenarios where the worldwide top-40 misses a city but the
    explicit city-filtered call finds it.
    """

    def __init__(
        self,
        responses: dict[str, list[OverpassWay]],
        city_responses: dict[tuple[str, str, str], list[OverpassWay]] | None = None,
    ) -> None:
        super().__init__(responses)
        self.city_responses = {
            (n.lower(), c, k): v for (n, c, k), v in (city_responses or {}).items()
        }
        self.city_calls: list[tuple[str, str, str]] = []

    def ways_named_in(self, name: str, city: str, country: str) -> list[OverpassWay]:
        self.city_calls.append((name, city, country))
        return list(self.city_responses.get((name.lower(), city, country), []))


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

    def test_two_pass_recovery_splices_hits_back_into_matches(self) -> None:
        """Phase 4a regression: when the worldwide top-40 misses the city for
        a common-name street (e.g. ``Victoria Street``), the two-pass-verify
        recovers the cluster via ``ways_named_in``. The recovered hits MUST be
        spliced back into the returned ``CrossRefResult.matches`` so that
        downstream GCP joiners can intersect against the cluster bbox.
        """
        # Worldwide pass: only the rare names hit anything in the right city;
        # ``Victoria Street`` returns 40 worldwide hits, none in St Albans.
        worldwide_victoria = [OverpassWay("Victoria Street",
                                          51.50 + 0.001 * i, -0.10 + 0.001 * i,
                                          city="London", country="UK")
                              for i in range(40)]
        client = FakeNominatimClient(
            responses={
                "Victoria Street": worldwide_victoria,
                "Jennings Road":   [OverpassWay("Jennings Road",  51.752, -0.339,
                                                city="St Albans", country="UK")],
                "Chiswell Green":  [OverpassWay("Chiswell Green", 51.738, -0.378,
                                                city="St Albans", country="UK")],
            },
            city_responses={
                # The city-filtered lookup IS aware of St Albans' Victoria St.
                ("Victoria Street", "St Albans", "UK"): [
                    OverpassWay("Victoria Street", 51.751, -0.341,
                                city="St Albans", country="UK"),
                ],
            },
        )
        result = find_geocode(
            [_candidate("Victoria Street", 1.0),
             _candidate("Jennings Road",   0.95),
             _candidate("Chiswell Green",  0.85)],
            client,                                                   # type: ignore[arg-type]
            min_streets=3,
            cluster_radius_km=3.0,
        )
        assert result.cluster is not None
        assert result.cluster.city == "St Albans"
        # The fix: matches["Victoria Street"] must now contain the
        # St Albans hit, not just the 40 London hits.
        st_albans_hits = [
            w for w in result.matches.get("Victoria Street", [])
            if w.city == "St Albans"
        ]
        assert len(st_albans_hits) == 1, (
            "Two-pass verification recovered Victoria Street in St Albans, "
            "but the recovered hit was not spliced back into matches — "
            "downstream GCP joiners will silently lose this anchor."
        )
        # And the worldwide London hits must still be there (additive splice).
        london_hits = [
            w for w in result.matches.get("Victoria Street", [])
            if w.city == "London"
        ]
        assert len(london_hits) == 40

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


# -------------------------- Phase 4c B1 — per-street node enumeration -------

class TestPerStreetNodeClient:
    """Cache-format tests for ``PerStreetNodeClient``.

    The network path is exercised indirectly via cache pre-population — same
    pattern as ``TestOverpassClientCache`` / ``TestNominatimStreetClientCache``:
    seed the on-disk cache, instantiate a fresh client, point ``_url`` at a
    dead address, and confirm the call short-circuits to the cached payload.
    """

    def test_positive_cache_replay_with_node_ids(self, tmp_path: Path) -> None:
        cache = tmp_path / "psn.json"
        client = PerStreetNodeClient(cache_path=cache, rate_limit_seconds=0.0)
        # Felix Road in some bbox — three OSM nodes
        key = client._cache_key("Felix Road", (51.50, 51.51, -0.21, -0.20))
        client._cache[key] = [
            {"node_id": 1001, "lat": 51.504, "lon": -0.207},
            {"node_id": 1002, "lat": 51.505, "lon": -0.206},
            {"node_id": 1003, "lat": 51.506, "lon": -0.205},
        ]
        client._save_cache()

        client2 = PerStreetNodeClient(cache_path=cache, rate_limit_seconds=0.0)
        client2._url = "http://127.0.0.1:1/never-listening"
        nodes = client2.nodes_for_street("Felix Road", (51.50, 51.51, -0.21, -0.20))
        assert len(nodes) == 3
        assert {n.node_id for n in nodes} == {1001, 1002, 1003}
        assert nodes[0].lat == pytest.approx(51.504)

    def test_negative_cache_replay_returns_empty_without_network(
        self, tmp_path: Path,
    ) -> None:
        cache = tmp_path / "psn.json"
        client = PerStreetNodeClient(cache_path=cache, rate_limit_seconds=0.0)
        bbox = (51.50, 51.51, -0.21, -0.20)
        client._negatives.add(client._cache_key("Noplace Road", bbox))
        client._save_cache()

        client2 = PerStreetNodeClient(cache_path=cache, rate_limit_seconds=0.0)
        client2._url = "http://127.0.0.1:1/never-listening"
        assert client2.nodes_for_street("Noplace Road", bbox) == []

    def test_cache_key_quantises_micro_jitter_in_bbox(
        self, tmp_path: Path,
    ) -> None:
        """Two bboxes that differ by 1e-5 (~1 m) should map to the same cache
        key — otherwise tiny float jitter in the cluster centroid busts every
        cache hit."""
        cache = tmp_path / "psn.json"
        client = PerStreetNodeClient(
            cache_path=cache, rate_limit_seconds=0.0, bbox_quantise=1e-3,
        )
        k1 = client._cache_key("Felix Road", (51.50001, 51.51001, -0.21001, -0.20001))
        k2 = client._cache_key("Felix Road", (51.50002, 51.51002, -0.21002, -0.20002))
        assert k1 == k2

    def test_bbox_in_key_isolates_caches_across_clusters(
        self, tmp_path: Path,
    ) -> None:
        """'Felix Road in cluster A' empty must not mask 'Felix Road in cluster B'.
        This is the bug the original Overpass cache schema would have had if we
        reused it — Overpass-with-bbox makes empty results bbox-specific."""
        cache = tmp_path / "psn.json"
        client = PerStreetNodeClient(cache_path=cache, rate_limit_seconds=0.0)
        bbox_a = (51.50, 51.51, -0.21, -0.20)
        bbox_b = (40.70, 40.71, -74.02, -74.01)
        # Felix Road in NYC bbox: cached with nodes
        client._cache[client._cache_key("Felix Road", bbox_b)] = [
            {"node_id": 2001, "lat": 40.705, "lon": -74.015},
        ]
        # Felix Road in London bbox: negative
        client._negatives.add(client._cache_key("Felix Road", bbox_a))
        client._save_cache()

        client2 = PerStreetNodeClient(cache_path=cache, rate_limit_seconds=0.0)
        client2._url = "http://127.0.0.1:1/never-listening"
        assert client2.nodes_for_street("Felix Road", bbox_a) == []
        nyc = client2.nodes_for_street("Felix Road", bbox_b)
        assert len(nyc) == 1
        assert nyc[0].node_id == 2001


class TestPickViaNodeForStreet:
    """The crossing-point selector that B1 uses to pin a via-node ON the
    cartoon's actual crossing of a named street, not Nominatim's centroid."""

    def test_picks_closest_node_to_polyline_vertex(self) -> None:
        # Three nodes along Felix Road. The polyline (cartoon) crosses near
        # node #2 (the middle one).
        nodes = [
            StreetNode(node_id=1, lat=51.500, lon=-0.210),
            StreetNode(node_id=2, lat=51.505, lon=-0.205),
            StreetNode(node_id=3, lat=51.510, lon=-0.200),
        ]
        polyline = [
            (51.520, -0.220),    # far away
            (51.505, -0.206),    # right next to node #2
            (51.530, -0.180),    # far away
        ]
        pick = pick_via_node_for_street(nodes, polyline)
        assert pick is not None
        assert pick.node_id == 2

    def test_empty_nodes_returns_none(self) -> None:
        assert pick_via_node_for_street(
            [], [(51.5, -0.2), (51.51, -0.21)],
        ) is None

    def test_empty_polyline_returns_none(self) -> None:
        nodes = [StreetNode(node_id=1, lat=51.5, lon=-0.2)]
        assert pick_via_node_for_street(nodes, []) is None

    def test_far_apart_polyline_still_picks_an_argmin(self) -> None:
        """Even when no node is anywhere near the polyline, the selector
        still returns the relatively-closest one — the caller (B1) decides
        whether the pick is good enough; this helper is just argmin."""
        nodes = [
            StreetNode(node_id=10, lat=51.500, lon=-0.210),
            StreetNode(node_id=11, lat=51.510, lon=-0.220),
        ]
        # 10 km away → both nodes are far, but #11 is closer to the polyline.
        polyline = [(51.600, -0.300)]
        pick = pick_via_node_for_street(nodes, polyline)
        assert pick is not None
        assert pick.node_id == 11
