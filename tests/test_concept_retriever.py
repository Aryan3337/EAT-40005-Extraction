"""Tests for rag.py's ConceptRetriever -- the CSV-backed fallback used when
AuraDB is unreachable.

WHY THIS EXISTS: ConceptRetriever had its own independent ranking, separate
from Neo4jRAGSkeleton.query's question_keywords/score_triple scoring, and by
its own old docstring scored partly on "length of sentence_ref (longer =
more context)". That rewards verbose citations -- precisely the pathology
MAX_SENTENCE_REF_CHARS exists to stop on the extraction side -- and meant the
fallback you would switch to under pressure on demo morning ranked answers
differently from the graph path it stands in for. ConceptRetriever now
scores through the same score_triple() the graph path uses.
"""

from rag import ConceptRetriever, DEFAULT_TOP_K


class _FakeKnowledgeGraph:
    """Duck-types the one thing ConceptRetriever.retrieve reads from a real
    KnowledgeGraph -- its triples list -- without needing a CSV on disk.
    """

    def __init__(self, triples):
        self.triples = triples


def _triple(**overrides):
    triple = {
        "subject": "GaroPeople",
        "predicate": "BILINGUAL",
        "object": "Bengali",
        "sentence_ref": "The majority of Garo people are bilingual.",
    }
    triple.update(overrides)
    return triple


def test_a_question_with_no_content_words_returns_nothing():
    retriever = ConceptRetriever(_FakeKnowledgeGraph([_triple()]))
    assert retriever.retrieve("What are they?") == []


def test_a_triple_matching_nothing_is_not_returned():
    retriever = ConceptRetriever(_FakeKnowledgeGraph([_triple()]))
    assert retriever.retrieve("What about marriage customs?") == []


def test_an_entity_match_outranks_a_citation_match():
    # Mirrors score_triple's own ranking behaviour: a triple ABOUT the thing
    # asked about should outrank one that merely mentions it in its citation.
    about = _triple(subject="Marriage", sentence_ref="Something unrelated.")
    mentions = _triple(subject="Unrelated", object="Unrelated",
                       predicate="X", sentence_ref="Marriage is discussed here.")
    retriever = ConceptRetriever(_FakeKnowledgeGraph([mentions, about]))
    assert retriever.retrieve("marriage")[0] == about


def test_a_long_winded_citation_no_longer_wins_on_length_alone():
    # The old scoring added len(sentence_ref) / 200 as a bonus, so a long but
    # weakly-relevant citation could outrank a short, directly relevant one.
    # score_triple carries no such bonus.
    short_and_relevant = _triple(subject="GaroLanguage", sentence_ref="Garo is a language.")
    long_and_vague = _triple(
        subject="Unrelated", object="Unrelated", predicate="X",
        sentence_ref="Garo " + ("filler word " * 60),
    )
    retriever = ConceptRetriever(_FakeKnowledgeGraph([long_and_vague, short_and_relevant]))
    assert retriever.retrieve("garo language")[0] == short_and_relevant


def test_duplicate_facts_from_different_passages_are_collapsed():
    first = _triple(sentence_ref="Passage one mentions it.")
    second = _triple(sentence_ref="Passage two mentions it too.")
    retriever = ConceptRetriever(_FakeKnowledgeGraph([first, second]))
    assert retriever.retrieve("bilingual") == [first]


def test_an_explicit_top_k_caps_the_number_of_results():
    # The /query handler relies on this: it now calls skeleton.query(...,
    # top_k=SYNTHESIS_EVIDENCE_LIMIT) so the "View verified sources" count
    # matches what synthesis actually saw (10) instead of the full
    # DEFAULT_TOP_K=25 retrieval -- see rag.py's do_POST for why.
    triples = [_triple(subject=f"GaroThing{i}") for i in range(20)]
    retriever = ConceptRetriever(_FakeKnowledgeGraph(triples))
    assert len(retriever.retrieve("garo", top_k=5)) == 5


def test_the_default_top_k_matches_the_graph_paths_default():
    retriever = ConceptRetriever(_FakeKnowledgeGraph([]))
    import inspect
    default = inspect.signature(retriever.retrieve).parameters["top_k"].default
    assert default == DEFAULT_TOP_K
