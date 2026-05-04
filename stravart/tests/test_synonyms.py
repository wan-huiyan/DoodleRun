from stravart.synonyms import resolve_category, CATEGORIES, SYNONYMS


def test_canonical_passthrough():
    assert resolve_category("birds") == "birds"
    assert resolve_category("cats-dogs") == "cats-dogs"


def test_common_synonyms():
    assert resolve_category("dog") == "cats-dogs"
    assert resolve_category("puppy") == "cats-dogs"
    assert resolve_category("cat") == "cats-dogs"
    assert resolve_category("dinosaur") == "dinosaurs"
    assert resolve_category("trex") == "dinosaurs"
    assert resolve_category("bee") == "insects"
    assert resolve_category("snake") == "reptiles"
    assert resolve_category("whale") == "sea-life"


def test_unknown_returns_none():
    assert resolve_category("xyzzy") is None
    assert resolve_category("") is None


def test_case_insensitive():
    assert resolve_category("DOG") == "cats-dogs"
    assert resolve_category("  Cat  ") == "cats-dogs"


def test_all_synonym_targets_are_canonical_categories():
    # Sanity: every synonym slug must be a real strav.art category
    for term, slug in SYNONYMS.items():
        assert slug in CATEGORIES, f"{term!r} -> {slug!r} not in CATEGORIES"
