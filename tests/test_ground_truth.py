from eval.ground_truth import parse_triple_string, parse_page_cell


def test_parse_triple_string_basic():
    result = parse_triple_string("(GaroCommunity)-[IS_ONE_OF]->(LargestMinorityTribes)")
    assert result == ("GaroCommunity", "IS_ONE_OF", "LargestMinorityTribes")


def test_parse_triple_string_no_match_returns_none():
    assert parse_triple_string("not a triple") is None


def test_parse_triple_string_empty_returns_none():
    assert parse_triple_string("") is None


def test_parse_page_cell_single_page():
    pages, section = parse_page_cell("page 3, Attire")
    assert pages == frozenset({"3"})
    assert section == "Attire"


def test_parse_page_cell_range():
    pages, section = parse_page_cell("page 4-5, Festival")
    assert pages == frozenset({"4", "5"})
    assert section == "Festival"


def test_parse_page_cell_empty():
    pages, section = parse_page_cell("")
    assert pages == frozenset()
    assert section is None
