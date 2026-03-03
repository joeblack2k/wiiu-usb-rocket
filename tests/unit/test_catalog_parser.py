from core.catalog.parser import parse_catalog_feed


def test_parse_catalog_feed_c_array_format() -> None:
    payload = r'''
    static const struct title_entry db[] = {
      {"0005000010101A00","Super Game","EUR","game"},
      {"0005000010101A01","Another\nGame","USA","dlc"}
    };
    '''

    items = parse_catalog_feed(payload)
    assert len(items) == 2
    assert items[0].title_id == "0005000010101a00"
    assert items[0].name == "Super Game"
    assert items[1].name == "Another\nGame"
    assert items[1].region == "USA"


def test_parse_catalog_feed_json_format() -> None:
    payload = '[{"title_id":"00050000AAAABBBB","name":"Json Title","region":"JPN","category":"game"}]'
    items = parse_catalog_feed(payload)
    assert len(items) == 1
    assert items[0].title_id == "00050000aaaabbbb"
    assert items[0].category == "game"


def test_parse_catalog_feed_vault_json_format() -> None:
    payload = '[{"titleID":"000500001010da00","name":"Minecraft: Wii U Edition","region":"EUR","ticket":"1"}]'
    items = parse_catalog_feed(payload)
    assert len(items) == 1
    assert items[0].title_id == "000500001010da00"
    assert items[0].name == "Minecraft: Wii U Edition"
    assert items[0].region == "EUR"
    assert items[0].category == "ticket"
