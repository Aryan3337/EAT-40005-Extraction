"""Tests for the topic filter on rag.py's graph retrieval path -- backlog G1.

WHY THIS EXISTS: KNOWN_LIMITATIONS 27. ConceptRetriever.retrieve has always
dropped triples that match the question's community-identity words but none
of its topic words; Neo4jRAGSkeleton.query -- the path the deployed system
actually uses -- never did. Measured 2026-10-27 on the live instance, that
asymmetry cost an answer: "What is the Garo population?" was REFUSED while
`Population_Census_2022 -[POPULATION]-> 1,650,159` sat first in the evidence
returned alongside the refusal, with nine off-topic triples behind it. The
working theory recorded in that entry is that the junk dilutes the evidence
block enough for the synthesis relevance gate to judge the whole set
irrelevant.

tools/compare_retrieval_paths.py measures the same gap over the CSV corpus
and reported off-topic = 27 across the eight benchmark questions before this
change.

WHAT THESE DO NOT COVER: Cypher semantics, for the same reason as
test_insert.py -- there is no Neo4j in the unit suite. These feed the rows
Cypher would return straight to the ranking code that consumes them.
"""

from rag import Neo4jRAGSkeleton, topic_focused


POPULATION = {
    "subject": "Population_Census_2022",
    "predicate": "POPULATION",
    "object": "1,650,159",
    "sentence_ref": "The Garo population was recorded as 1,650,159.",
}

# The four highest-scoring off-topic triples the live run returned for the
# population question, verbatim from KNOWN_LIMITATIONS 27.
LANGUAGE_JUNK = [
    {
        "subject": "Garo_People",
        "predicate": "BILINGUAL",
        "object": "Garo_Language",
        "sentence_ref": "The Garo people are bilingual.",
    },
    {
        "subject": "GaroCommunity",
        "predicate": "LANGUAGE_USED",
        "object": "Garo",
        "sentence_ref": "The Garo community uses Garo.",
    },
    {
        "subject": "GaroCommunity",
        "predicate": "HAS_LANGUAGE_Maintenance",
        "object": "GaroLanguage",
        "sentence_ref": "Language maintenance in the Garo community.",
    },
    {
        "subject": "GaroCommunity",
        "predicate": "RESIDENTS",
        "object": "GaroHills_Meghalaya",
        "sentence_ref": "Residents of the Garo Hills, Meghalaya.",
    },
]


class FakeSession:
    """Returns canned rows for any query, and records what it was asked."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        return list(self.rows)


class FakeDriver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


def _skeleton(rows):
    """A Neo4jRAGSkeleton wired to canned rows.

    Bypasses __init__ deliberately: it requires the neo4j package and a
    complete URI/USERNAME/PASSWORD config, neither of which the unit suite
    has, and query() reads nothing from the instance but self.driver.
    """
    skeleton = object.__new__(Neo4jRAGSkeleton)
    skeleton.driver = FakeDriver(FakeSession(rows))
    return skeleton


def test_off_topic_triples_are_dropped_from_the_graph_path():
    """The limitation 27 reproduction: the answer survives, the junk does not."""
    skeleton = _skeleton([POPULATION] + LANGUAGE_JUNK)

    results = skeleton.query("What is the Garo population?")

    assert [triple["predicate"] for triple in results] == ["POPULATION"]


def test_the_answer_is_still_returned_when_it_ranks_below_the_junk():
    """Ordering must not decide whether the filter keeps the right triple."""
    skeleton = _skeleton(LANGUAGE_JUNK + [POPULATION])

    results = skeleton.query("What is the Garo population?")

    assert [triple["predicate"] for triple in results] == ["POPULATION"]


def test_nothing_on_topic_leaves_the_results_alone():
    """Precision over recall is the house posture, but this filter is not the
    place to enforce it: emptying the evidence here would turn a weak answer
    into a refusal with no evidence shown at all. ConceptRetriever keeps the
    unfiltered set in this case and the graph path must agree with it."""
    skeleton = _skeleton(list(LANGUAGE_JUNK))

    results = skeleton.query("What is the Garo population?")

    assert len(results) == len(LANGUAGE_JUNK)


def test_community_identity_alone_is_not_a_topic():
    """"Garo", "people" and "community" match most of the graph, so letting
    them establish relevance would keep everything and filter nothing."""
    assert topic_focused(["garo", "people", "community"], LANGUAGE_JUNK) == LANGUAGE_JUNK


def test_a_question_that_is_only_identity_words_filters_nothing():
    skeleton = _skeleton([POPULATION] + LANGUAGE_JUNK)

    results = skeleton.query("Who are the Garo people?")

    assert len(results) == len(LANGUAGE_JUNK) + 1


def test_the_shared_filter_matches_on_a_source_sentence():
    """A triple whose entities miss the topic but whose cited sentence carries
    it is on-topic -- the graph's predicate names are too terse to rely on."""
    buried = {
        "subject": "GaroCommunity",
        "predicate": "HAS_PROPERTY",
        "object": "unknown",
        "sentence_ref": "The population of the community is growing.",
    }

    assert topic_focused(["garo", "population"], [buried]) == [buried]


# ---------------------------------------------------------------------------
# The `score > 0` cut, the CSV path's other missing filter (backlog G1 step 3).
#
# Measured at zero effect on the eight benchmark questions, and kept anyway
# for the reason the backlog gives: Cypher's WHERE matches over `passage` and
# the topic filter reads `question`, neither of which is in _FIELD_WEIGHTS, so
# a row can satisfy both and still score nothing. Not a measured win -- a
# guard on a path the corpus does not currently exercise.
# ---------------------------------------------------------------------------


def test_a_triple_scoring_nothing_is_dropped_even_when_it_is_on_topic():
    """Community data carries a `question` column. The topic filter reads it;
    scoring does not. Such a row would otherwise reach synthesis with a
    relevance of zero."""
    question_only = {
        "subject": "Record_07",
        "predicate": "REPORTED",
        "object": "yes",
        "sentence_ref": "",
        "question": "What is the population of your village?",
    }
    skeleton = _skeleton([POPULATION, question_only])

    results = skeleton.query("What is the Garo population?")

    assert [triple["predicate"] for triple in results] == ["POPULATION"]


def test_a_triple_matching_only_its_passage_is_dropped():
    """Cypher's WHERE matches `passage`, which carries no score. With nothing
    on topic the filter falls back to the whole set, so the cut is the only
    thing standing between a zero-scoring row and the evidence block."""
    passage_only = {
        "subject": "Unrelated",
        "predicate": "MENTIONS",
        "object": "nothing",
        "sentence_ref": "",
        "passage": "A paragraph that happens to mention population.",
    }
    skeleton = _skeleton([passage_only])

    results = skeleton.query("What is the Garo population?")

    assert results == []
