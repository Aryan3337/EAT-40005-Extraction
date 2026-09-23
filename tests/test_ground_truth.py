from eval.ground_truth import (
    parse_triple_string,
    parse_page_cell,
    DEFAULT_GT_PATH,
    load_final_triples,
    load_sentences,
    triples_for_pages,
)


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


def test_load_sentences_finds_known_sentence():
    sentences = load_sentences(DEFAULT_GT_PATH)
    pages, section, text = sentences["S1"]
    assert pages == frozenset({"1"})
    assert "largest minority tribes" in text.lower()


def test_load_final_triples_total_count():
    triples = load_final_triples(DEFAULT_GT_PATH)
    assert len(triples) == 148


def test_load_final_triples_page3_subset_count():
    triples = load_final_triples(DEFAULT_GT_PATH)
    page3 = triples_for_pages(triples, ["3"])
    assert len(page3) == 23


def test_load_final_triples_rows_without_sentence_have_no_pages():
    triples = load_final_triples(DEFAULT_GT_PATH)
    no_page = [t for t in triples if not t.pages]
    assert len(no_page) == 12


def test_load_final_triples_fields_populated():
    triples = load_final_triples(DEFAULT_GT_PATH)
    first = next(t for t in triples if t.ref == "R1")
    assert first.subject == "GaroCommunity"
    assert first.predicate == "IS_ONE_OF"
    assert first.object == "LargestMinorityTribes"
    assert first.pages == frozenset({"1"})
