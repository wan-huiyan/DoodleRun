"""Unit tests for street-name detection + abbreviation expansion."""

from __future__ import annotations

import pytest

from stravart.streets import (
    StreetCandidate,
    filter_street_candidates,
    looks_like_street,
    parse_street,
)


class TestLooksLikeStreet:
    """``looks_like_street`` is the cheap pre-filter used to drop OCR junk
    before the more expensive parse_street call."""

    @pytest.mark.parametrize("s", [
        "Broomfield Rd",
        "Partridge Ave",
        "Skerry Road",
        "Eves Cr",
        "Dixon Avenue",
        "Boarded Barns Lane",
        "St Andrews Way",
        "rue Lafayette",
        "Tauentzienstrasse",
        "Calle Mayor",
        "Via Roma",
        "via Roma",                       # case-insensitive
        "The Avenue",                     # short prefix is fine
        "First Ave.",                     # trailing period
    ])
    def test_accepts(self, s: str) -> None:
        assert looks_like_street(s)

    @pytest.mark.parametrize("s", [
        "",
        " ",
        "Andrews Park Lake",              # Lake isn't in suffix table
        "Scot's Green",                   # 'Green' is a suffix - test in opposite list below
        "PARK",                           # one token, no prefix
        "1234",
        "x",
        "this string is way too long " * 5,
    ])
    def test_rejects(self, s: str) -> None:
        # For the deliberate-edge "Scot's Green" we DO want a hit since Green
        # is a recognised suffix; flip it out of the rejects set:
        if s == "Scot's Green":
            assert looks_like_street(s)
        else:
            assert not looks_like_street(s)


class TestParseStreet:
    """parse_street is the producer of normalised candidates the cross-ref
    module hits Overpass with — abbreviation expansion is load-bearing."""

    def test_expands_rd_to_road(self) -> None:
        c = parse_street("Broomfield Rd", confidence=0.91)
        assert c is not None
        assert c.normalized == "Broomfield Road"
        assert c.suffix == "road"
        assert c.confidence == pytest.approx(0.91)
        assert c.raw == "Broomfield Rd"

    def test_expands_ave_to_avenue(self) -> None:
        c = parse_street("Partridge Ave")
        assert c is not None and c.normalized == "Partridge Avenue"

    def test_expands_cr_to_crescent(self) -> None:
        c = parse_street("Eves Cr")
        assert c is not None and c.normalized == "Eves Crescent"

    def test_keeps_full_form(self) -> None:
        c = parse_street("Skerry Road")
        assert c is not None and c.normalized == "Skerry Road"

    def test_handles_multiword_prefix(self) -> None:
        c = parse_street("Boarded Barns Lane")
        assert c is not None and c.normalized == "Boarded Barns Lane"

    def test_handles_german_strasse_with_eszett(self) -> None:
        # Compound form is valid — "Tauentzienstraße" → normalize ß to ss.
        c = parse_street("Tauentzienstraße")
        assert c is not None
        assert c.normalized == "Tauentzienstrasse"
        assert c.suffix == "strasse"

    def test_handles_german_compound_str_form(self) -> None:
        c = parse_street("Friedrichstrasse")
        assert c is not None and c.normalized == "Friedrichstrasse"

    def test_handles_french_leading(self) -> None:
        c = parse_street("rue Lafayette")
        assert c is not None and c.normalized == "Rue Lafayette"
        assert c.suffix == "rue"

    def test_handles_italian_leading(self) -> None:
        c = parse_street("Via Roma")
        assert c is not None and c.normalized == "Via Roma"

    def test_strips_quotes_and_brackets(self) -> None:
        c = parse_street('"Dixon Ave"')
        assert c is not None and c.normalized == "Dixon Avenue"

    def test_returns_none_for_garbage(self) -> None:
        assert parse_street("") is None
        assert parse_street("XYZZY") is None
        assert parse_street("Park")  is None    # one token, no prefix


class TestFilterCandidates:
    """The filter dedupes and sorts the candidates the cross-ref hits Overpass
    with — wrong order = wasted Overpass quota on the lowest-quality reads."""

    def test_drops_low_confidence(self) -> None:
        out = filter_street_candidates(
            [("Broomfield Rd", 0.95), ("Junky St", 0.10)],
            min_confidence=0.30,
        )
        assert [c.normalized for c in out] == ["Broomfield Road"]

    def test_dedupes_keeping_highest_confidence(self) -> None:
        out = filter_street_candidates([
            ("broomfield rd", 0.40),
            ("Broomfield Rd", 0.95),
            ("BROOMFIELD ROAD", 0.85),
        ])
        assert len(out) == 1
        assert out[0].confidence == pytest.approx(0.95)

    def test_sorted_by_descending_confidence(self) -> None:
        out = filter_street_candidates([
            ("Eves Cr",        0.55),
            ("Broomfield Rd",  0.95),
            ("Partridge Ave",  0.78),
        ])
        assert [c.confidence for c in out] == [0.95, 0.78, 0.55]

    def test_drops_non_streets(self) -> None:
        out = filter_street_candidates([
            ("ANDREWS",         0.99),
            ("PARK",            0.99),
            ("Broomfield Rd",   0.50),
        ])
        assert [c.normalized for c in out] == ["Broomfield Road"]
