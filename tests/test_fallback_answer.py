"""Tests for rag.py's AnswerSynthesizer._fallback_answer and its helpers --
the templated answer shown when live synthesis is unreachable or disabled.

WHY THIS EXISTS: there was no test coverage for this at all before
2026-10-07, despite it being KNOWN_LIMITATIONS.md #19 ("hosted answers read
poorly"). A live user report ("What is the Garo community?" -> "The Garo
people faces Unemployment. ... The Gari people residents Garo Hills
Meghalaya.") traced to two real, confirmed bugs, both fixed here:

1. The old 8-entry template dict matched NONE of the real production
   graph's 32 predicates -- including a literal typo, "LIVE_IN" against the
   real "LIVING_IN" -- so every answer fell through to naive
   subject-predicate-object concatenation with no verb-number agreement:
   "The Garo people faces Unemployment" (should be "face").
2. _humanize_entity collapsed a bare "Garo" to "the Garo people" whether it
   was used as a subject OR an object. For LANGUAGE_USED ("GaroCommunity
   -> Garo", meaning the Garo LANGUAGE), the object collapsed the same way,
   producing a self-referential sentence: "The Garo people language used
   The Garo people."
"""

import csv
from pathlib import Path

from rag import AnswerSynthesizer

PRODUCTION_GRAPH_DIR = Path(__file__).resolve().parent.parent / "data" / "production_graph"


def _synthesizer() -> AnswerSynthesizer:
    # __new__, not AnswerSynthesizer(...): these tests exercise pure string
    # formatting and should not need a real or mocked Ollama endpoint.
    return AnswerSynthesizer.__new__(AnswerSynthesizer)


def _triple(**overrides):
    triple = {
        "subject": "GaroCommunity",
        "predicate": "FACES",
        "object": "Unemployment",
    }
    triple.update(overrides)
    return triple


def _production_graph_rows():
    rows = []
    for paper in ("garo_1", "garo_2", "garo_3"):
        path = PRODUCTION_GRAPH_DIR / f"{paper}_kg_refined.csv"
        with open(path, encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    return rows


# -- the two exact bugs a live user hit, as a permanent regression lock ------


def test_a_plural_subject_gets_the_bare_verb_not_the_singular_form():
    # The exact live bug report, 2026-10-07: GaroCommunity -> "the Garo
    # people" (plural-reading), so FACES must render as "face", not
    # "faces".
    synthesizer = _synthesizer()
    sentence = synthesizer._format_triple(_triple(predicate="FACES", object="Unemployment"))
    assert sentence == "The Garo people face Unemployment."
    assert "faces" not in sentence.lower()


def test_a_bare_garo_object_reads_as_the_language_not_the_people():
    # The exact live bug report, 2026-10-07: LANGUAGE_USED's object "Garo"
    # was collapsing to "the Garo people" just like the subject did,
    # producing "The Garo people language used The Garo people".
    synthesizer = _synthesizer()
    sentence = synthesizer._format_triple(
        _triple(subject="GaroCommunity", predicate="LANGUAGE_USED", object="Garo")
    )
    assert sentence == "The Garo people speak Garo."


def test_a_garo_subject_still_reads_as_the_people():
    # The object-side fix must not break the (still wanted) subject-side
    # collapse -- "Garo" alone as a SUBJECT should still mean the people.
    synthesizer = _synthesizer()
    humanized = synthesizer._humanize_entity("Garo")
    assert humanized == "The Garo people"


# -- _is_plural_subject --------------------------------------------------------


def test_people_is_recognized_as_plural():
    synthesizer = _synthesizer()
    assert synthesizer._is_plural_subject("The Garo people") is True


def test_a_named_singular_entity_is_not_plural():
    synthesizer = _synthesizer()
    assert synthesizer._is_plural_subject("Judgment") is False


def test_a_subject_ending_in_s_that_is_actually_singular_is_not_misflagged():
    # Real counter-example from the production graph: "Garo Community
    # Health Status" ends in "s" but is singular (an uncountable status, not
    # a group). A blanket "ends in s" rule would misfire here -- checked
    # deliberately when choosing the curated suffix list over that rule.
    synthesizer = _synthesizer()
    assert synthesizer._is_plural_subject("Garo Community Health Status") is False


# -- every predicate in the real production graph -----------------------------


def test_every_real_predicate_has_a_dedicated_template():
    # Locks in that the current 45-triple production graph's 32 predicates
    # are all explicitly covered -- none silently falls through to the
    # generic word-segmentation path. A new paper adding a new predicate is
    # expected to fail this test until a template is added for it (or it is
    # accepted as falling through to the generic path on purpose).
    synthesizer = _synthesizer()
    rows = _production_graph_rows()
    assert rows, "expected real production graph CSVs to be present"
    missing = sorted({
        row["predicate"] for row in rows
        if row["predicate"].upper().replace(" ", "_") not in synthesizer._PREDICATE_TEMPLATES
    })
    assert missing == []


def test_every_real_triple_formats_without_crashing_and_ends_with_a_period():
    synthesizer = _synthesizer()
    for row in _production_graph_rows():
        sentence = synthesizer._format_triple(row)
        assert sentence.endswith(".")
        assert len(sentence) > 1


def test_no_real_triple_produces_the_old_broken_patterns():
    # The two concrete, confirmed failure signatures from the live bug
    # report, swept across the WHOLE real graph, not just the one triple
    # that happened to be reported.
    synthesizer = _synthesizer()
    for row in _production_graph_rows():
        sentence = synthesizer._format_triple(row)
        assert "people faces" not in sentence.lower()
        assert "people residents" not in sentence.lower()
        assert "language used the garo people" not in sentence.lower()


def test_a_fallback_answer_over_the_real_graph_reads_as_sentences():
    # End-to-end sanity check matching how the live chatbot actually calls
    # this: a handful of real triples retrieved for a question, rendered as
    # one answer.
    synthesizer = _synthesizer()
    rows = [row for row in _production_graph_rows() if row["subject"] == "GaroCommunity"
            or row["subject"] == "Garo_People"][:4]
    answer = synthesizer._fallback_answer(rows)
    assert answer.startswith("Based on the available knowledge, ")
    assert "faces" not in answer.lower()


# -- the generic fallback path (a predicate NOT in _PREDICATE_TEMPLATES) ------


def test_an_unknown_predicate_is_still_plural_aware():
    # A future paper's new predicate isn't in _PREDICATE_TEMPLATES, so it
    # falls through to _humanize_predicate's word-segmentation path. That
    # path must still get verb number right for the common single-word-verb
    # case, or the exact same class of bug reappears on the next paper.
    synthesizer = _synthesizer()
    sentence = synthesizer._format_triple(
        _triple(subject="GaroCommunity", predicate="CELEBRATES", object="Wangala")
    )
    assert sentence == "The Garo people celebrate Wangala."


def test_an_unknown_predicates_multiword_trailing_plural_noun_is_not_mangled():
    # The scoping guard on the single-segment heuristic: "identified
    # domains" must not become "identified domain" for a plural subject --
    # the trailing "s" there is a plural NOUN (the object of the verb
    # "identified"), not a verb needing de-pluralization.
    synthesizer = _synthesizer()
    readable = synthesizer._humanize_predicate("identified domains", is_plural=True)
    assert readable == "identified domains"


def test_an_unknown_predicate_for_a_singular_subject_is_unchanged():
    synthesizer = _synthesizer()
    sentence = synthesizer._format_triple(
        _triple(subject="Judgment", predicate="CELEBRATES", object="Wangala")
    )
    assert sentence == "Judgment celebrates Wangala."
