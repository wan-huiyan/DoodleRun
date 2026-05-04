"""Heuristic parser: strav.art image alt text -> (shape, city, country).

strav.art titles are not structured. Most look like one of:

    "AVENUE DOG"                          # shape only
    "MANCHESTER DOG"                      # CITY SHAPE
    "PARIS CAT — FRANCE"                  # SHAPE — COUNTRY (em dash)
    "ST ALBANS LION"                      # multi-word city + shape
    "OFFICIAL BIG DOG 2023"               # noisy/promotional
    "BOGGLE-EYED CAT 🐱"                   # emoji + decorations
    "Tuesday Evening Run"                 # no useful location

We extract a *candidate* city string with a fixed gazetteer of common UK + global
cities (focus area: Hertfordshire, outer London, Milton Keynes per Phase 1 spec)
and fall back to a token-based guess. The output is fed to Nominatim for the
authoritative lat/lon — confidence-flagged when the heuristic is shaky.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Cities the user explicitly cares about for Phase 1 (focus area), plus common
# global cities that frequently appear in strav.art titles. We match longer names
# first to avoid "ST ALBANS" being eaten by "ALBANS".
KNOWN_CITIES: tuple[tuple[str, str | None], ...] = (
    # Phase 1 focus area
    ("ST ALBANS", "United Kingdom"),
    ("MILTON KEYNES", "United Kingdom"),
    ("HERTFORDSHIRE", "United Kingdom"),
    ("HEMEL HEMPSTEAD", "United Kingdom"),
    ("WATFORD", "United Kingdom"),
    ("LUTON", "United Kingdom"),
    ("HARPENDEN", "United Kingdom"),
    ("STEVENAGE", "United Kingdom"),
    # London + UK
    ("LONDON", "United Kingdom"),
    ("MANCHESTER", "United Kingdom"),
    ("LIVERPOOL", "United Kingdom"),
    ("BIRMINGHAM", "United Kingdom"),
    ("LEEDS", "United Kingdom"),
    ("BRISTOL", "United Kingdom"),
    ("EDINBURGH", "United Kingdom"),
    ("GLASGOW", "United Kingdom"),
    ("CARDIFF", "United Kingdom"),
    ("BRIGHTON", "United Kingdom"),
    ("OXFORD", "United Kingdom"),
    ("CAMBRIDGE", "United Kingdom"),
    ("YORK", "United Kingdom"),
    ("BATH", "United Kingdom"),
    # Europe
    ("AMSTERDAM", "Netherlands"),
    ("ROTTERDAM", "Netherlands"),
    ("UTRECHT", "Netherlands"),
    ("PARIS", "France"),
    ("BERLIN", "Germany"),
    ("MUNICH", "Germany"),
    ("HAMBURG", "Germany"),
    ("MADRID", "Spain"),
    ("BARCELONA", "Spain"),
    ("ROME", "Italy"),
    ("MILAN", "Italy"),
    ("VIENNA", "Austria"),
    ("PRAGUE", "Czechia"),
    ("WARSAW", "Poland"),
    ("STOCKHOLM", "Sweden"),
    ("OSLO", "Norway"),
    ("COPENHAGEN", "Denmark"),
    ("HELSINKI", "Finland"),
    ("DUBLIN", "Ireland"),
    ("LISBON", "Portugal"),
    ("BRUSSELS", "Belgium"),
    ("ZURICH", "Switzerland"),
    # North America
    ("NEW YORK", "United States"),
    ("LOS ANGELES", "United States"),
    ("SAN FRANCISCO", "United States"),
    ("CHICAGO", "United States"),
    ("BOSTON", "United States"),
    ("SEATTLE", "United States"),
    ("PORTLAND", "United States"),
    ("AUSTIN", "United States"),
    ("DENVER", "United States"),
    ("MIAMI", "United States"),
    ("TORONTO", "Canada"),
    ("VANCOUVER", "Canada"),
    ("MONTREAL", "Canada"),
    # Asia/Pacific
    ("TOKYO", "Japan"),
    ("OSAKA", "Japan"),
    ("KYOTO", "Japan"),
    ("SEOUL", "South Korea"),
    ("SHANGHAI", "China"),
    ("BEIJING", "China"),
    ("HONG KONG", "Hong Kong"),
    ("SINGAPORE", "Singapore"),
    ("BANGKOK", "Thailand"),
    ("SYDNEY", "Australia"),
    ("MELBOURNE", "Australia"),
    ("BRISBANE", "Australia"),
    ("PERTH", "Australia"),
    ("AUCKLAND", "New Zealand"),
    ("WELLINGTON", "New Zealand"),
)

# Words that look like cities to a naive matcher but rarely are, for the
# token-based fallback. Lowercase.
COMMON_NON_PLACES: frozenset[str] = frozenset({
    "big", "small", "happy", "sad", "official", "national", "morning",
    "evening", "afternoon", "sunday", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "fast", "slow", "quick", "long",
    "short", "the", "and", "or", "of", "in", "on", "with", "for",
    "run", "ride", "jog", "walk", "art", "strava", "doodle", "today",
    "yesterday", "tomorrow", "new", "old", "good", "bad", "best",
    "first", "last", "year", "day", "week", "month", "fun", "cool",
})

# Em/en-dash, pipe, slash, or comma separator between shape and location.
# Plain hyphens are excluded because they appear inside compound words
# (e.g. "BOGGLE-EYED CAT") and would split shape names mid-token.
_SEPARATORS = re.compile(r"\s*[–—―,|/]\s*")
_EMOJI_AND_PUNCT = re.compile(
    r"[\U00010000-\U0010ffff\U0001f300-\U0001fad9☀-➿!?()\[\]{}\"'*#~]+",
    flags=re.UNICODE,
)
_WHITESPACE = re.compile(r"\s+")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")

# Sort by length descending so "NEW YORK" wins over "YORK", "ST ALBANS" over
# "ALBANS" (etc). Done once at import time.
_CITIES_LONGEST_FIRST: tuple[tuple[str, str | None], ...] = tuple(
    sorted(KNOWN_CITIES, key=lambda c: -len(c[0]))
)


@dataclass(frozen=True)
class TitleParse:
    raw: str
    shape: str          # cleaned title text without the city
    city: str | None
    country: str | None
    confidence: float   # 0.0 = no city, 0.5 = token guess, 1.0 = gazetteer hit


def _clean(text: str) -> str:
    text = _EMOJI_AND_PUNCT.sub(" ", text or "")
    text = _YEAR.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def parse_title(raw: str) -> TitleParse:
    """Best-effort parse of a strav.art image alt text.

    The cleaned `shape` field is the raw title minus a recognised city/country.
    `confidence` reflects how sure we are about the city — gazetteer hits are
    canonical, single-token guesses get demoted, no-match returns 0.0 and the
    geocoder is skipped entirely.
    """
    if not raw:
        return TitleParse(raw="", shape="", city=None, country=None, confidence=0.0)

    cleaned = _clean(raw)
    upper = cleaned.upper()

    # 1) Gazetteer scan, longest-first to win on multi-word cities.
    for city, country in _CITIES_LONGEST_FIRST:
        # Whole-word boundary so "MILTON" doesn't eat into "MILTON KEYNES" matches
        # we already passed (we iterate longest-first, so once matched we're done).
        pat = re.compile(r"(?<![A-Z])" + re.escape(city) + r"(?![A-Z])")
        m = pat.search(upper)
        if m:
            shape = (upper[: m.start()] + " " + upper[m.end():]).strip()
            shape = _SEPARATORS.sub(" ", shape).strip()
            shape = _WHITESPACE.sub(" ", shape).strip()
            return TitleParse(
                raw=raw, shape=shape or upper, city=city.title(),
                country=country, confidence=1.0,
            )

    # 2) Em-dash / hyphen split: "SHAPE — CITY" or "SHAPE, CITY"
    parts = _SEPARATORS.split(upper)
    if len(parts) >= 2:
        # Last segment is most likely the location
        candidate = parts[-1].strip()
        toks = candidate.split()
        if 1 <= len(toks) <= 3 and not any(t.lower() in COMMON_NON_PLACES for t in toks):
            shape = " ".join(parts[:-1]).strip()
            return TitleParse(
                raw=raw, shape=shape, city=candidate.title(),
                country=None, confidence=0.5,
            )

    # 3) No location signal.
    return TitleParse(
        raw=raw, shape=upper, city=None, country=None, confidence=0.0,
    )
