"""Tests for rag.py's retrieval scoring.

WHY: measured on the 16 gated garo_1 triples, the keyword "garo" matches 13
of them -- already above the old top_k of 10. And ORDER BY relevance was
near-inert: the hardcoded relationship_terms looked for
speak/language/dialect, population, live/locat/resid, is_a/type in the
predicate name, but the graph's actual predicates are LANGUAGE_USED,
HAS_LANGUAGE_Maintenance, EXTENT_OF_USE, IS_USED_IN, HAS_TRADITIONAL_RELIGION
and so on. Only POPULATION matched any term, so 10 of 11 predicate types
scored 0, the ordering was a tie, and the chatbot returned whatever order
Neo4j happened to scan in.

That is a defect today, not at scale: it degrades answer quality with no
error and no slowdown, which is why it never showed up as a complaint. At 20
more papers it becomes an arbitrary 10 of roughly 200.
"""

from rag import DEFAULT_TOP_K, dedupe_triples, question_keywords, resolve_port, score_triple


def _triple(**overrides):
    triple = {
        "subject": "GaroPeople",
        "predicate": "BILINGUAL",
        "object": "Bengali",
        "sentence_ref": "The majority of Garo people are bilingual.",
    }
    triple.update(overrides)
    return triple


# -- question_keywords --------------------------------------------------------


def test_keywords_are_lowercased_content_words():
    assert question_keywords("What language do the Garo speak?") == \
        ["language", "garo", "speak"]


def test_stopwords_are_dropped():
    # The old regex kept any word of 3+ characters, so "what", "are", "the"
    # and "and" became keywords -- and those match nearly every sentence_ref
    # in the graph, which is a large part of why retrieval matched so broadly.
    assert question_keywords("What are the Garo and their land?") == ["garo", "land"]


def test_very_short_words_are_dropped():
    assert question_keywords("Do we go to it?") == []


def test_a_question_with_no_content_words_yields_nothing():
    # The caller returns no triples rather than matching the whole graph.
    assert question_keywords("What are they?") == []


def test_duplicates_are_collapsed_but_order_is_kept():
    assert question_keywords("Garo land and Garo language") == \
        ["garo", "land", "language"]


# -- score_triple -------------------------------------------------------------


def test_a_triple_matching_nothing_scores_zero():
    assert score_triple(_triple(), ["marriage"]) == 0


def test_an_entity_match_outranks_a_citation_match():
    # A triple ABOUT the thing asked about should beat one that merely
    # mentions it in passing in its source sentence.
    about = _triple(subject="Marriage", sentence_ref="Something unrelated.")
    mentions = _triple(subject="Unrelated", object="Unrelated",
                       predicate="X", sentence_ref="Marriage is discussed here.")
    assert score_triple(about, ["marriage"]) > score_triple(mentions, ["marriage"])


def test_a_predicate_match_outranks_a_citation_match():
    on_predicate = _triple(predicate="HAS_MARRIAGE_CUSTOM", sentence_ref="x")
    in_citation = _triple(predicate="X", sentence_ref="Marriage customs vary.")
    assert score_triple(on_predicate, ["marriage"]) > score_triple(in_citation, ["marriage"])


def test_more_matched_keywords_scores_higher_than_fewer():
    both = _triple(subject="GaroLanguage", object="Bengali")
    one = _triple(subject="GaroLanguage", object="Unrelated")
    assert score_triple(both, ["garo", "bengali"]) > score_triple(one, ["garo", "bengali"])


def test_scoring_is_case_insensitive():
    assert score_triple(_triple(subject="GAROPEOPLE"), ["garo"]) > 0


def test_a_missing_field_does_not_crash_scoring():
    # Rows come back from Cypher with coalesce defaults, but a CSV-backed row
    # can genuinely lack sentence_ref.
    assert score_triple({"subject": "GaroPeople"}, ["garo"]) > 0


def test_predicates_the_old_hardcoded_list_could_never_match_now_score():
    # These are real predicates from the gated corpus, each paired with a
    # word a user would plausibly ask with. Under the old relationship_terms
    # none of them scored, so they tied at zero with everything else -- the
    # list looked for "speak"/"dialect"/"is_a", which appear in none of them.
    cases = [
        ("LANGUAGE_USED", "language"),
        ("HAS_LANGUAGE_Maintenance", "language"),
        ("EXTENT_OF_USE", "use"),
        ("HAS_TRADITIONAL_RELIGION", "religion"),
        ("HAS_HEALTH_STATUS", "health"),
    ]
    for predicate, keyword in cases:
        assert score_triple(_triple(predicate=predicate), [keyword]) > 0, predicate


# -- the top_k default --------------------------------------------------------


def test_the_default_top_k_exceeds_the_measured_match_count():
    # 13 of 16 garo_1 triples match "garo", so a top_k of 10 silently
    # discarded real evidence on the most obvious question anyone would ask.
    assert DEFAULT_TOP_K > 13


# -- dedupe_triples ------------------------------------------------------------


def test_identical_facts_from_different_passages_are_collapsed():
    first = _triple(sentence_ref="Passage one mentions it.")
    second = _triple(sentence_ref="Passage two mentions it too.")
    assert dedupe_triples([first, second]) == [first]


def test_the_first_occurrence_is_kept_not_the_last():
    # The caller sorts by score before deduping, so "first" means
    # highest-ranked -- this just locks in that dedupe does not reorder.
    best = _triple(sentence_ref="best")
    worst = _triple(sentence_ref="worst")
    assert dedupe_triples([best, worst]) == [best]


def test_facts_that_differ_in_any_field_are_both_kept():
    a = _triple(object="Bengali")
    b = _triple(object="English")
    assert dedupe_triples([a, b]) == [a, b]


def test_an_empty_list_stays_empty():
    assert dedupe_triples([]) == []


# -- resolve_port ---------------------------------------------------------


def test_an_explicit_port_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("PORT", "9999")
    assert resolve_port(8080) == 8080


def test_the_platforms_injected_port_is_used_when_none_is_given(monkeypatch):
    # Render, Railway and Fly.io all inject $PORT for a web service.
    monkeypatch.setenv("PORT", "9999")
    assert resolve_port(None) == 9999


def test_the_default_is_8000_when_neither_is_set(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert resolve_port(None) == 8000
