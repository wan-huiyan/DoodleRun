"""Street-name shape detection + abbreviation expansion.

Strav.art maps render street labels in many languages but the suffix tells you
*it's a street*: "Rd", "Ave", "Ln", "Boulevard", "Strasse", "Rue", etc. We use
a curated suffix table both to (a) filter raw OCR fragments down to plausible
street names and (b) expand short forms into the canonical strings that
Nominatim / Overpass actually store.

This module is intentionally network-free and has zero heavy deps so the
unit tests can run anywhere.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Suffixes whose canonical form sits at the END of the street name (English +
# Commonwealth + most Germanic-rooted languages). Each entry is
# ``(token_in_text, canonical)`` — match is case-insensitive.
_TRAILING_SUFFIXES: tuple[tuple[str, str], ...] = (
    # English
    ("rd",          "road"),
    ("road",        "road"),
    ("st",          "street"),
    ("street",      "street"),
    ("ave",         "avenue"),
    ("av",          "avenue"),
    ("avenue",      "avenue"),
    ("ln",          "lane"),
    ("lane",        "lane"),
    ("dr",          "drive"),
    ("drive",       "drive"),
    ("blvd",        "boulevard"),
    ("boulevard",   "boulevard"),
    ("cl",          "close"),
    ("close",       "close"),
    ("cres",        "crescent"),
    ("cr",          "crescent"),
    ("crescent",    "crescent"),
    ("ct",          "court"),
    ("court",       "court"),
    ("pl",          "place"),
    ("place",       "place"),
    ("sq",          "square"),
    ("square",      "square"),
    ("way",         "way"),
    ("walk",        "walk"),
    ("park",        "park"),
    ("green",       "green"),
    ("hill",        "hill"),
    ("gdns",        "gardens"),
    ("gardens",     "gardens"),
    ("mews",        "mews"),
    ("terrace",     "terrace"),
    ("ter",         "terrace"),
    ("row",         "row"),
    ("path",        "path"),
    ("rise",        "rise"),
)

# Suffixes that lead the street name in their language ("Rue Lafayette",
# "Via Roma"). Stored separately because the regex shape is different.
_LEADING_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("rue",      "rue"),
    ("calle",    "calle"),
    ("avenida",  "avenida"),
    ("plaza",    "plaza"),
    ("via",      "via"),
    ("viale",    "viale"),
    ("piazza",   "piazza"),
)

# Suffixes that may be glued to the previous word as one token, German-style
# ("Tauentzienstrasse"). We require ≥3 letters of "name" before the suffix
# so that "strasse" alone doesn't match — and so common false positives like
# "thestrasse" stay out.
_COMPOUND_TRAILING: tuple[tuple[str, str], ...] = (
    ("strasse",  "strasse"),
    ("straße",   "strasse"),
)

# Combined for backwards compat with looks_like_street and tests that probe
# the canonical-suffix table.
_SUFFIXES: tuple[tuple[str, str], ...] = _TRAILING_SUFFIXES + _LEADING_SUFFIXES + _COMPOUND_TRAILING

_TRAILING_SET = {s for s, _ in _TRAILING_SUFFIXES}
_LEADING_SET  = {s for s, _ in _LEADING_SUFFIXES}
_COMPOUND_SET = {s for s, _ in _COMPOUND_TRAILING}
_EXPAND_MAP   = dict(_SUFFIXES)

# Allow letters from any Latin-script European language (Strav.art posts cover
# UK, FR, DE, ES, IT, etc.). The "name" can include apostrophes and hyphens.
_NAME_TOKEN = r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’\.\-]*"

# 1) Standard trailing-suffix form: "Broomfield Rd", "St Andrews Way".
_TRAILING_PATTERN = re.compile(
    rf"^(?:{_NAME_TOKEN}\s+){{0,4}}{_NAME_TOKEN}\s+([A-Za-z]{{1,12}})\.?$"
)

# 2) Leading-suffix form: "Rue Lafayette", "Via Roma", "Calle Mayor".
_LEADING_PATTERN = re.compile(
    rf"^([A-Za-z]{{2,8}})\s+{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,4}}\.?$"
)

# 3) Glued-compound form: "Tauentzienstrasse", "Friedrichstraße".
#    Require ≥3 letters of name preceding the suffix so we don't match the
#    bare suffix on its own (i.e. "strasse" → no match).
_COMPOUND_PATTERN = re.compile(
    r"^([A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'\-]{2,})(strasse|straße)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StreetCandidate:
    """OCR fragment that looks like a street name.

    `raw` is what the OCR returned. `normalized` is the form we will look up
    via OSM — suffix expanded ("Rd" → "Road"), surrounding noise stripped.
    """

    raw: str
    normalized: str
    suffix: str            # canonical, e.g. "road", "avenue"
    confidence: float      # OCR confidence 0..1


def _strip_quotes(s: str) -> str:
    return s.strip().strip("\"'`“”‘’()[]{}<>")


def _collapse_ws(s: str) -> str:
    return " ".join(s.split())


def _ascii_fold(s: str) -> str:
    """Best-effort fold to ASCII for suffix matching (Bréf → Bref)."""
    nf = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in nf if not unicodedata.combining(ch))


def _classify(text: str) -> tuple[str, str, str] | None:
    """Return ``(prefix_or_name, canonical_suffix, kind)`` or None.

    ``kind`` is one of ``trailing``, ``leading``, ``compound`` so the caller
    can re-assemble the normalised form correctly per language.
    """
    # Trailing English/UK form first (most common in our corpus).
    m = _TRAILING_PATTERN.match(text)
    if m:
        suffix_raw = m.group(1)
        key = _ascii_fold(suffix_raw).lower().rstrip(".")
        canonical = _EXPAND_MAP.get(key)
        if canonical and key in _TRAILING_SET:
            prefix = text[: m.start(1)].rstrip()
            if prefix:
                return prefix, canonical, "trailing"

    # Leading EU form.
    m = _LEADING_PATTERN.match(text)
    if m:
        head = _ascii_fold(m.group(1)).lower().rstrip(".")
        canonical = _EXPAND_MAP.get(head)
        if canonical and head in _LEADING_SET:
            tail = text[m.end(1):].strip().rstrip(".")
            if tail:
                return tail, canonical, "leading"

    # German-style glued compound.
    m = _COMPOUND_PATTERN.match(text)
    if m:
        name = m.group(1)
        suffix_raw = m.group(2)
        key = _ascii_fold(suffix_raw).lower()
        canonical = _EXPAND_MAP.get(key)
        if canonical and key in _COMPOUND_SET:
            return name, canonical, "compound"

    return None


def looks_like_street(text: str) -> bool:
    """Cheap pre-filter: does this string look like a street name?"""
    s = _collapse_ws(_strip_quotes(text))
    if not s or len(s) > 60:
        return False
    return _classify(s) is not None


def parse_street(text: str, confidence: float = 1.0) -> StreetCandidate | None:
    """Return a StreetCandidate if `text` is street-shaped, else None.

    Handles three syntactic shapes (trailing, leading, glued-compound) and
    re-assembles the canonical form so Overpass sees the spelling OSM stores:

      * "Broomfield Rd"     → "Broomfield Road"      (trailing)
      * "rue Lafayette"     → "Rue Lafayette"        (leading)
      * "Tauentzienstrasse" → "Tauentzienstrasse"    (compound, normalised case)
    """
    s = _collapse_ws(_strip_quotes(text))
    if not s:
        return None
    cls = _classify(s)
    if cls is None:
        return None
    name_part, canonical, kind = cls
    if kind == "trailing":
        normalized = f"{name_part.title()} {canonical.title()}"
    elif kind == "leading":
        normalized = f"{canonical.title()} {name_part.title()}"
    else:  # compound
        normalized = f"{name_part.title()}{canonical}"
    return StreetCandidate(
        raw=s,
        normalized=normalized,
        suffix=canonical,
        confidence=confidence,
    )


def filter_street_candidates(
    fragments: list[tuple[str, float]],
    *,
    min_confidence: float = 0.30,
) -> list[StreetCandidate]:
    """Return street candidates from ``[(text, confidence), ...]``.

    Deduplicates on the *normalized* form, keeping the highest-confidence
    instance of each street. We sort by descending confidence so the first
    cross-reference attempt uses our most-trusted reads.
    """
    seen: dict[str, StreetCandidate] = {}
    for text, conf in fragments:
        if conf < min_confidence:
            continue
        cand = parse_street(text, conf)
        if cand is None:
            continue
        existing = seen.get(cand.normalized.lower())
        if existing is None or cand.confidence > existing.confidence:
            seen[cand.normalized.lower()] = cand
    return sorted(seen.values(), key=lambda c: -c.confidence)
