#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Tests for the hybrid keyword + semantic retrieval path."""

import csv
import math

import pytest

import embeddings
from embeddings import TripleEmbeddingIndex

import rag
from rag import (
    ConceptRetriever,
    KnowledgeGraph,
    reciprocal_rank_fusion,
    _semantic_candidate_indices,
)


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
    monkeypatch.setattr(embeddings, "embed_text", _fake_embed)
    return _fake_embed


@pytest.fixture
def no_community_filter(monkeypatch):
    monkeypatch.setattr(rag, "filter_community_periods", lambda triples, q: triples)


@pytest.fixture
def kg(tmp_path, no_community_filter):
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


def test_rrf_prefers_items_present_in_both_lists():
    fused = reciprocal_rank_fusion([[10, 20, 30], [20, 10, 40]])
    assert fused[10] > fused[30]
    assert fused[20] > fused[40]


def test_rrf_with_empty_second_list_returns_first_order():
    fused = reciprocal_rank_fusion([[5, 3, 1], []])
    assert sorted(fused.keys(), key=lambda i: -fused[i]) == [5, 3, 1]


def test_semantic_indices_map_onto_candidate_subset(kg, index):
    candidates = kg.triples[1:]
    mapped = _semantic_candidate_indices(index, "Garo religion", candidates, kg.triples)
    assert all(0 <= i < len(candidates) for i in mapped)


def test_semantic_indices_empty_when_no_index(kg):
    assert _semantic_candidate_indices(None, "anything", kg.triples, kg.triples) == []


def test_keyword_only_misses_quantity_paraphrase(kg):
    retriever = ConceptRetriever(kg, embedding_index=None)
    triples = retriever.retrieve("How many people live there?", top_k=5)
    assert "POPULATION" not in [t["predicate"] for t in triples]


def test_semantic_recovers_quantity_paraphrase(kg, index):
    retriever = ConceptRetriever(kg, embedding_index=index)
    triples = retriever.retrieve("How many people live there?", top_k=5)
    assert "POPULATION" in {t["predicate"] for t in triples}


def test_keyword_still_wins_on_exact_entity_name(kg, index):
    retriever = ConceptRetriever(kg, embedding_index=index)
    triples = retriever.retrieve("What is GaroCommunity?", top_k=5)
    assert triples[0]["subject"].lower() == "garocommunity"


def test_retriever_works_with_no_embedding_index(kg):
    retriever = ConceptRetriever(kg, embedding_index=None)
    triples = retriever.retrieve("Where do the Garo people live?", top_k=5)
    assert "LIVING_IN" in {t["predicate"] for t in triples}


def test_empty_semantic_ranking_fuses_to_keyword_order(kg):
    keyword_only = ConceptRetriever(kg, embedding_index=None).retrieve(
        "What is the Garo language?", top_k=5
    )

    class DeadIndex:
        def semantic_ranking(self, question, **kwargs):
            return []

    fused = ConceptRetriever(kg, embedding_index=DeadIndex()).retrieve(
        "What is the Garo language?", top_k=5
    )
    assert [t["predicate"] for t in keyword_only] == [t["predicate"] for t in fused]


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
        assert len(calls) == len(kg.triples)

        calls.clear()
        idx2 = TripleEmbeddingIndex(cache_dir=tmp_path / "emb")
        idx2.build_or_load(kg.triples)
        assert calls == []
        assert idx2.vectors == idx.vectors
    finally:
        emb_module.embed_text = original


def test_build_raises_when_embedding_unavailable(kg, monkeypatch, tmp_path):
    monkeypatch.setattr(embeddings, "embed_text", lambda _: None)
    idx = TripleEmbeddingIndex(cache_dir=tmp_path / "emb")
    with pytest.raises(RuntimeError):
        idx.build_or_load(kg.triples)
