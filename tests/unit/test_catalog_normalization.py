"""Tests voor catalog normalisatie: name, region, lege velden."""
from core.catalog.parser import parse_catalog_feed


def test_name_leading_trailing_whitespace_stripped() -> None:
    payload = '[{"title_id":"0005000010101a00","name":"  Super Game  ","region":"EUR","category":"game"}]'
    items = parse_catalog_feed(payload)
    assert items[0].name == "Super Game"


def test_name_internal_newline_normalized() -> None:
    payload = '[{"title_id":"0005000010101a00","name":"Super\\nGame","region":"EUR","category":"game"}]'
    items = parse_catalog_feed(payload)
    assert items[0].name == "Super Game"


def test_region_unknown_value_becomes_unk() -> None:
    payload = '[{"title_id":"0005000010101a00","name":"X","region":"AUS","category":"game"}]'
    items = parse_catalog_feed(payload)
    assert items[0].region == "UNK"


def test_region_empty_becomes_unk() -> None:
    payload = '[{"title_id":"0005000010101a00","name":"X","region":"","category":"game"}]'
    items = parse_catalog_feed(payload)
    assert items[0].region == "UNK"


def test_region_whitelist_preserved() -> None:
    for region in ("EUR", "USA", "JPN", "ALL", "UNK"):
        payload = f'[{{"title_id":"0005000010101a00","name":"X","region":"{region}","category":"game"}}]'
        items = parse_catalog_feed(payload)
        assert items[0].region == region


def test_region_case_insensitive_normalization() -> None:
    payload = '[{"title_id":"0005000010101a00","name":"X","region":"eur","category":"game"}]'
    items = parse_catalog_feed(payload)
    assert items[0].region == "EUR"


def test_missing_name_falls_back_to_empty_string() -> None:
    payload = '[{"title_id":"0005000010101a00","region":"EUR","category":"game"}]'
    items = parse_catalog_feed(payload)
    assert items[0].name == ""


def test_null_name_falls_back_to_empty_string() -> None:
    payload = '[{"title_id":"0005000010101a00","name":null,"region":"EUR","category":"game"}]'
    items = parse_catalog_feed(payload)
    assert items[0].name == ""


def test_empty_category_becomes_unknown() -> None:
    payload = '[{"title_id":"0005000010101a00","name":"X","region":"EUR","category":""}]'
    items = parse_catalog_feed(payload)
    assert items[0].category == "unknown"
