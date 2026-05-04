from stravart.parse_title import parse_title


def test_gazetteer_hit_uk_city():
    p = parse_title("MANCHESTER DOG")
    assert p.city == "Manchester"
    assert p.country == "United Kingdom"
    assert p.confidence == 1.0
    assert "DOG" in p.shape
    assert "MANCHESTER" not in p.shape


def test_multi_word_city_st_albans():
    p = parse_title("ST ALBANS LION 2024")
    assert p.city == "St Albans"
    assert p.country == "United Kingdom"
    assert p.confidence == 1.0
    assert "LION" in p.shape
    assert "ST" not in p.shape.split()


def test_milton_keynes_not_eaten_by_milton():
    p = parse_title("MILTON KEYNES BIRD")
    assert p.city == "Milton Keynes"
    assert p.confidence == 1.0


def test_em_dash_split_lowconf():
    p = parse_title("CARTOON CAT — TOKYO")
    # TOKYO is in the gazetteer, so this resolves to a high-confidence hit
    assert p.city == "Tokyo"
    assert p.country == "Japan"
    assert p.confidence == 1.0


def test_em_dash_unknown_city_lowconf():
    p = parse_title("WIGGLY DOG — SMALLTOWN")
    assert p.city == "Smalltown"
    assert p.confidence == 0.5


def test_no_location():
    p = parse_title("YORKIE")
    assert p.city is None
    assert p.country is None
    assert p.confidence == 0.0
    assert p.shape == "YORKIE"


def test_emoji_stripping():
    p = parse_title("BOGGLE-EYED CAT 🐱")
    assert "🐱" not in p.shape
    assert "CAT" in p.shape


def test_empty_input():
    p = parse_title("")
    assert p.city is None
    assert p.confidence == 0.0


def test_promo_text_no_false_positive():
    # "OFFICIAL BIG DOG 2023" has none of our gazetteer cities
    p = parse_title("OFFICIAL BIG DOG 2023")
    assert p.city is None
    # year stripped
    assert "2023" not in p.shape


def test_us_city():
    p = parse_title("NEW YORK DOG")
    assert p.city == "New York"
    assert p.country == "United States"
