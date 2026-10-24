#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for the hybrid keyword + semantic retrieval path.

These use a deterministic bag-of-words embedding with synonym folding
(_fake_embed below) rather than calling Ollama, so the suite runs offline
and in well under a second. The fake's job is only to prove that the
fusion behaves correctly -- when semantic ranking recovers a paraphrase,
when keyword ranking still wins on exact entity names, and when a missing
embedding degrades cleanly to keyword-only. Whether a real embedding model
recovers real paraphrases is a question for a labelled evaluation set, not
a unit test.
"""

import csv
import math

import pytest

import embeddings
from embeddings import TripleEmbeddingIndex, triple_text

import rag
from rag import ConceptRetriever, KnowledgeGraph, reciprocal_rank_fusion


# ---------------------------------------------------------------------------
# Deterministic fake embedding: bag-of-words with synonym folding.
# ---------------------------------------------------------------------------

_SYNONYM_GROUPS = [
    ("population", "many", "number", "headcount", "inhabitants", "size", "populous"),
    ("live", "reside", "inhabit", "dwell", "living", "lives", "lived"),
    ("religion", "religious", "belief", "faith", "worship", "traditional"),
    ("language", "speak", "dialect", "tongue", "linguistic"),
    ("garo", "achik", "mande", "mandi"),
    ("community", "communities", "group", "people"),
    ("festival", "celebrate", "celebration", "wangala"),
]


def _fake_embed(text: str):
    lowered = text.lower()
    vector = []
    for group in _SYNONYM_GROUPS:
        count = sum(lowered.count(word) for word in group)
        vector.append(float(count))
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Replace the real Ollama call before any index is built."""
    monkeypatch.setattr(embeddings, "embed_text", _fake_embed)
    return _fake_embed


# ---------------------------------------------------------------------------
# A small graph that contains one triple per test scenario.
# ---------------------------------------------------------------------------

@pytest.fixture
def kg(tmp_path):
    csv_path = tmp_path / "kg.csv"
    rows = [
        ["subject", "predicate", "object", "sentence_ref", "source_section", "confidence"],
        ["GaroCommunity", "POPULATION", "about three million",
         "The Garo population is about three million in Meghalaya.", "Demographics", "High"],
        ["GaroCommunity", "LIVING_IN", "Meghalaya",
         "Most Garo people live in Meghalaya.", "Location", "High"],
        ["GaroCommunity", "HAS_TRADITIONAL_RELIGION", "Songsarek",
         "The traditional Garo religion is Songsarek.", "Religion", "High"],
        ["GaroCommunity", "LANGUAGE_USED", "Garo",
         "The Garo community speaks the Garo language.", "Language", "High"],
        ["GaroCommunity", "CELEBRATES", "Wangala",
         "The Wangala festival is celebrated by the Garo community.", "Festival", "High"],
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return KnowledgeGraph(str(csv_path))


@pytest.fixture
def index(kg, fake_embeddings, tmp_path):
    idx = TripleEmbeddingIndex(cache_dir=tmp_path / "emb")
    idx.build_or_load(kg.triples)
    return idx


# ---------------------------------------------------------------------------
# RRF itself -- pure function, no fixtures needed.
# ---------------------------------------------------------------------------

def test_rrf_prefers_items_present_in_both_lists():
    keyword = [10, 20, 30]
    semantic = [20, 10, 40]
    fused = reciprocal_rank_fusion([keyword, semantic])
    # 10 and 20 appear in both lists, 30 and 40 in only one.
    assert fused[10] > fused[30]
    assert fused[20] > fused[40]


def test_rrf_with_empty_semantic_returns_keyword_order():
    keyword = [5, 3, 1]
    fused = reciprocal_rank_fusion([keyword, []])
    ordered = sorted(fused.keys(), key=lambda i: -fused[i])
    assert ordered == [5, 3, 1]


# ---------------------------------------------------------------------------
# The behaviour this whole change exists to produce.
# ---------------------------------------------------------------------------

def test_keyword_only_misses_quantity_paraphrase(kg):
    """Without semantic search, 'how many people live there' does not match
    the POPULATION triple: 'many' and 'there' are stopwords, and the
    POPULATION row contains neither 'people' nor 'live'."""
    retriever = ConceptRetriever(kg, embedding_index=None)
    triples = retriever.retrieve("How many people live there?", top_k=5)
    predicates = [t["predicate"] for t in triples]
    assert "POPULATION" not in predicates


def test_semantic_recovers_quantity_paraphrase(kg, index):
    """With semantic search fused in, the POPULATION triple is retrieved
    even though the question shares no literal keyword with it."""
    retriever = ConceptRetriever(kg, embedding_index=index)
    triples = retriever.retrieve("How many people live there?", top_k=5)
    predicates = {t["predicate"] for t in triples}
    assert "POPULATION" in predicates


def test_keyword_still_wins_on_exact_entity_name(kg, index):
    """Semantic search is additive, not a replacement: an exact entity-name
    question must still rank that entity's triple first."""
    retriever = ConceptRetriever(kg, embedding_index=index)
    triples = retriever.retrieve("What is GaroCommunity?", top_k=5)
    assert triples[0]["subject"].lower() == "garocommunity"


def test_both_rankers_agree_on_religion_question(kg, index):
    retriever = ConceptRetriever(kg, embedding_index=index)
    triples = retriever.retrieve(
        "What is the traditional religion of the Garo people?", top_k=5
    )
    assert triples[0]["predicate"] == "HAS_TRADITIONAL_RELIGION"


# ---------------------------------------------------------------------------
# Degradation: a missing embedding must never break retrieval.
# ---------------------------------------------------------------------------

def test_build_raises_when_embedding_unavailable(kg, monkeypatch, tmp_path):
    monkeypatch.setattr(embeddings, "embed_text", lambda _: None)
    idx = TripleEmbeddingIndex(cache_dir=tmp_path / "emb")
    with pytest.raises(RuntimeError):
        idx.build_or_load(kg.triples)


def test_retriever_works_with_no_embedding_index(kg):
    """The exact pre-semantic behaviour, preserved as the fallback path."""
    retriever = ConceptRetriever(kg, embedding_index=None)
    triples = retriever.retrieve("Where do the Garo people live?", top_k=5)
    predicates = {t["predicate"] for t in triples}
    assert "LIVING_IN" in predicates


def test_empty_semantic_ranking_fuses_to_keyword_order(kg):
    """An index that returns [] (embeddings down at query time) must not
    change the keyword ranking at all."""
    retriever = ConceptRetriever(kg, embedding_index=None)
    keyword_only = retriever.retrieve("What is the Garo language?", top_k=5)
    # Same question, but with a stub index that claims embeddings are down.
    class DeadIndex:
        def semantic_ranking(self, question, **kwargs):
            return []
    retriever_with_dead = ConceptRetriever(kg, embedding_index=DeadIndex())
    fused = retriever_with_dead.retrieve("What is the Garo language?", top_k=5)
    assert [t["predicate"] for t in keyword_only] == [t["predicate"] for t in fused]


# ---------------------------------------------------------------------------
# Cache behaviour -- only changed rows should be re-embedded.
# ---------------------------------------------------------------------------

def test_cache_reuses_unchanged_vectors(kg, fake_embeddings, tmp_path):
    calls = []
    original = _fake_embed

    def counting_embed(text):
        calls.append(text)
        return original(text)

    import embeddings as emb_module
    emb_module.embed_text = counting_embed
    try:
        idx = TripleEmbeddingIndex(cache_dir=tmp_path / "emb")
        idx.build_or_load(kg.triples)
        first_pass = len(calls)
        assert first_pass == len(kg.triples)

        # A second index over the same triples should hit the cache.
        calls.clear()
        idx2 = TripleEmbeddingIndex(cache_dir=tmp_path / "emb")
        idx2.build_or_load(kg.triples)
        assert calls == []
        assert idx2.vectors == idx.vectors
    finally:
        emb_module.embed_text = original