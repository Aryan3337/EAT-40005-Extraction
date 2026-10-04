"""Tests for verification/gate.py -- the one place the three deterministic
gates are run over a list of triples. Both run_verification_pipeline.py (CSV
in, CSV out) and main.py (in-memory dicts, straight to Neo4j) go through it,
so the hard-gate semantics are defined once rather than copied per caller."""

import pytest

from verification.gate import (
    apply_gates,
    page_number_from_source_section,
    sentence_for_row,
)


def _row(**overrides):
    row = {
        "subject": "GaroMen",
        "predicate": "WEAR",
        "object": "Lungis",
        "sentence_ref": "Garo men wear lungis.",
        "source_section": "Page 1",
        "page_number": "1",
    }
    row.update(overrides)
    return row


PAGE_TEXTS = {1: "Garo men wear lungis. They also wear shirts."}


# -- page_number_from_source_section ------------------------------------------


def test_page_number_is_read_out_of_the_source_section_string():
    # kg_extractor emits source_section="Page 3", not a page_number column,
    # but quote_check needs an int-parseable page to look up that page's text.
    assert page_number_from_source_section("Page 3") == "3"


def test_page_number_falls_back_to_zero_when_the_section_has_no_digits():
    assert page_number_from_source_section("Unknown") == "0"
    assert page_number_from_source_section("") == "0"
    assert page_number_from_source_section(None) == "0"


# -- sentence_for_row ---------------------------------------------------------


def test_sentence_prefers_sentence_ref_over_passage():
    row = _row(sentence_ref="the real citation", passage="the triple string")
    assert sentence_for_row(row) == "the real citation"


def test_sentence_falls_back_to_passage_when_sentence_ref_is_empty():
    row = _row(sentence_ref="", passage="fallback text")
    assert sentence_for_row(row) == "fallback text"


# -- apply_gates --------------------------------------------------------------


def test_a_clean_row_survives_every_gate():
    outcome = apply_gates([_row()], page_texts=PAGE_TEXTS, quote=True)
    assert len(outcome.kept) == 1
    assert outcome.flagged == {}


def test_a_wellformedness_failure_is_excluded_and_recorded():
    # Subject and Object restate the same concept -- the tautology rule.
    row = _row(subject="TypesOfBaskets", object="DifferentTypesOfBaskets")
    outcome = apply_gates([row], page_texts=PAGE_TEXTS, quote=True)
    assert outcome.kept == []
    assert len(outcome.flagged["wellformedness"]) == 1
    assert "tautological" in outcome.flagged["wellformedness"][0]["flag_reason"]


def test_an_ungrounded_subject_is_excluded_and_recorded():
    row = _row(subject="FloatingIsland")
    outcome = apply_gates([row])
    assert outcome.kept == []
    assert "FloatingIsland" in outcome.flagged["grounding"][0]["flag_reason"]


def test_a_citation_absent_from_its_page_is_excluded_and_recorded():
    row = _row(sentence_ref="Garo men wear top hats.")
    outcome = apply_gates([row], page_texts=PAGE_TEXTS, quote=True)
    assert outcome.kept == []
    assert len(outcome.flagged["quote"]) == 1


def test_a_row_failing_two_gates_is_recorded_under_both():
    # The flag files are an audit trail, not a first-match-wins dispatch:
    # a row rejected for two reasons must be traceable from either gate.
    row = _row(subject="TypesOfBaskets", object="DifferentTypesOfBaskets",
               sentence_ref="Garo men wear lungis.")
    outcome = apply_gates([row], page_texts=PAGE_TEXTS, quote=True)
    assert outcome.kept == []
    assert len(outcome.flagged["wellformedness"]) == 1
    assert len(outcome.flagged["grounding"]) == 1


def test_a_disabled_gate_does_not_reject():
    row = _row(subject="FloatingIsland")
    outcome = apply_gates([row], grounding=False)
    assert len(outcome.kept) == 1


def test_quote_gate_without_page_texts_is_a_programming_error():
    with pytest.raises(ValueError, match="page_texts"):
        apply_gates([_row()], quote=True)


def test_flagging_never_mutates_the_caller_s_row():
    row = _row(subject="FloatingIsland")
    apply_gates([row])
    assert "flag_reason" not in row


def test_counts_summarises_the_outcome():
    rows = [_row(), _row(subject="FloatingIsland")]
    outcome = apply_gates(rows)
    assert outcome.counts == {
        "refined": 1,
        "wellformedness_flags": 0,
        "grounding_flags": 1,
        "quote_flags": 0,
    }


def test_rows_missing_a_page_number_do_not_crash_the_quote_gate():
    # main.py's triples carry source_section but no page_number until it is
    # derived; a row that slipped through without one must fail closed, not
    # raise and take the whole run down.
    row = _row(page_number="")
    outcome = apply_gates([row], page_texts=PAGE_TEXTS, quote=True)
    assert outcome.kept == []
    assert len(outcome.flagged["quote"]) == 1
