#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RAG Query Layer – Prototype and Compare Two Retrieval Approaches

This module implements a minimal retrieval‑only layer for a knowledge graph (KG).
It supports two retrieval strategies:
    1. Concept Matching (default) – fast, entity‑based retrieval with fallbacks.
    2. Cypher Translation – uses a local LLM to generate a query from the question.

The script can run in three modes:
    - Comparison mode (–test-questions) : evaluates both approaches on a predefined set of questions.
    - Single‑query mode (–query)       : retrieves triples for one question.
    - Interactive mode (no flags)      : continuous question‑answering loop.

The comparison produces a data‑driven rationale that justifies the choice of Concept Matching
as the primary retrieval strategy for the current KG.
"""

import os
import json
import csv
import math
import re
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from urllib.parse import parse_qs, unquote, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple, Optional, Protocol, Union
from collections import defaultdict
from dotenv import load_dotenv
import requests

from admin_ingest import (check_admin_secret, current_queue, ingest_pdf,
                          read_paper_bytes, record_manual_decision,
                          validate_upload)
from auth_store import AuthStore
from llm_endpoint import ollama_tunnel_headers, resolve_llm_endpoint
import local_tts
from source_provenance import provenance_fields
from community_time import filter_community_periods
from community_attribution import group_responses, source_response_answer

try:
    from neo4j import GraphDatabase  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency for Neo4j mode
    GraphDatabase = None

# Load the .env that sits next to this file, whatever directory the server was
# started from, and let it win over a stale or empty variable already set in
# the shell. Without this the admin endpoints could report that
# ADMIN_UPLOAD_SECRET is unset even though .env has it.
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)


# ============================================================================
# Retrieval scoring
# ============================================================================

# Measured on the 16 gated garo_1 triples: the keyword "garo" matches 13 of
# them. A top_k of 10 therefore discarded real evidence on the most obvious
# question anyone would ask, silently.
DEFAULT_TOP_K = 25

# The old keyword regex kept every word of 3+ characters, so "what", "are",
# "the" and "and" became search terms -- and those appear in nearly every
# sentence_ref, which is much of why retrieval matched so broadly.
_STOPWORDS = {
    "the", "and", "are", "was", "were", "what", "who", "whom", "whose", "which",
    "how", "why", "when", "where", "does", "did", "for", "with", "about", "from",
    "into", "that", "this", "these", "those", "their", "them", "they", "there",
    "have", "has", "had", "can", "could", "would", "should", "will", "shall",
    "you", "your", "our", "its", "his", "her", "him", "she", "any", "all",
    "but", "not", "than", "then", "also", "some", "more", "most", "many",
    "tell", "give", "show", "say", "said", "know", "please", "thing", "things",
}


def question_keywords(question: str) -> List[str]:
    """Content words from the question, lowercased, duplicates collapsed.

    Order is preserved so the scoring is deterministic and reproducible for
    a given question.
    """
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", question or "")
    keywords = []
    for word in words:
        lowered = word.lower()
        if lowered in _STOPWORDS or lowered in keywords:
            continue
        keywords.append(lowered)
    return keywords


# Where a keyword matches decides how much it counts. A triple ABOUT the
# thing asked about should beat one that merely mentions it in passing in its
# source sentence. The previous scoring looked for a fixed list of terms in
# the predicate NAME -- speak/language/dialect, population, live/locat --
# against a graph whose predicates are LANGUAGE_USED, EXTENT_OF_USE,
# HAS_LANGUAGE_Maintenance and so on. Only POPULATION ever matched, so 10 of
# 11 predicate types scored 0 and ORDER BY relevance was a tie across almost
# everything, leaving Neo4j's scan order to pick the answer.
_FIELD_WEIGHTS = (("subject", 3), ("object", 3), ("predicate", 2), ("sentence_ref", 1))


def score_triple(triple: Dict[str, Any], keywords: List[str]) -> int:
    """How well one triple answers a question, given its content words."""
    score = 0
    for field, weight in _FIELD_WEIGHTS:
        haystack = str(triple.get(field) or "").lower()
        if not haystack:
            continue
        for keyword in keywords:
            if keyword in haystack:
                score += weight
    return score


# Keyword -> other word forms that should count as the same match. WHY A
# CURATED LIST, NOT A GENERAL STEMMING RULE: tried a shared-prefix heuristic
# first (e.g. "match if two words share a long enough common prefix") and
# measured it before shipping -- it still MISSES "live"/"living" under a
# safe threshold (their shared prefix "liv" is too short to pass safely),
# and under a looser threshold it produces real false positives on this
# exact corpus: "status" matches "statute", "family" matches "familiar",
# and "community" matches "communicate" (which would partially UNDO this
# morning's fix, since "Insufficient Communication" is a real object value
# and "community" is already the graph's most over-matching word). Same
# lesson as _PLURAL_SUBJECT_SUFFIXES: a bounded, curated list beats a
# general rule that misfires on this graph. Confirmed live 2026-10-07:
# "live" is not a literal substring of "living" (silent-e), and
# "religious" is not a literal substring of "religion" -- both caused a
# real triple (LIVING_IN, HAS_TRADITIONAL_RELIGION) to under-rank.
_KEYWORD_EQUIVALENTS: Dict[str, Tuple[str, ...]] = {
    "live": ("living", "lived", "lives"),
    "religious": ("religion", "religions"),
}

# Words that would substring-match a keyword but mean something unrelated --
# the same false-positive family _KEYWORD_EQUIVALENTS' docstring already
# warns about ("community" in "communicate"), found live 2026-10-08 on the
# overnight batch's new LivelihoodPatterns/MAINLYREFERS triples: "live" is a
# literal substring of "livelihood", so every one of those 8 triples
# false-matched "Where do the Garo live?" at the same score as the real
# LIVING_IN triple, and (being 8 near-identical rows -- see dedupe_triples)
# crowded the genuinely relevant RESIDENTS triple out of the top 10. Stripped
# from the haystack before matching, the same way a stopword is removed,
# rather than blocked with a word-boundary regex -- entity names like
# "GaroCommunity" rely on substring matching across a camelCase join with no
# boundary, so a general regex fix would break those matches too.
_KEYWORD_FALSE_POSITIVES: Dict[str, Tuple[str, ...]] = {
    "live": ("livelihood", "livelihoods"),
}


def _keyword_matches(keyword: str, haystack: str) -> bool:
    for excluded in _KEYWORD_FALSE_POSITIVES.get(keyword, ()):
        haystack = haystack.replace(excluded, "")
    if keyword in haystack:
        return True
    return any(form in haystack for form in _KEYWORD_EQUIVALENTS.get(keyword, ()))


def _keyword_in_triple(triple: Dict[str, Any], keyword: str) -> bool:
    for field, _ in _FIELD_WEIGHTS:
        if _keyword_matches(keyword, str(triple.get(field) or "").lower()):
            return True
    return False


def keyword_weights(keywords: List[str], triples: List[Dict[str, Any]]) -> Dict[str, float]:
    """How much each keyword should count in score_triple_weighted, discounted
    by how common it is across `triples` -- a classic smoothed IDF.

    WHY: measured 2026-10-07 on the real 45-triple production graph, "garo"
    appears in 22 of 45 triples and "community" in 17, because GaroCommunity
    is the graph's one hub entity (13 of 45 triples). Under flat scoring, a
    triple that only matches on "garo"/"community" outranks one that matches
    a genuinely rare, on-topic word like "religious" (3 of 45) or
    "traditional" (2 of 45) -- so a specific question gets buried in generic
    hub noise. Confirmed live: a religion question retrieved no real religion
    evidence, and the model invented a speculative connection to compensate
    (see tests/test_answer_synthesis.py's synthesis tests) -- the model was
    honest given what it was handed, it just was not handed the right
    evidence. A keyword present in every triple contributes a weight just
    above 1 (counts, but barely); one present in only one or two triples
    contributes several times that.
    """
    n = len(triples) or 1
    weights = {}
    for keyword in keywords:
        document_frequency = sum(1 for triple in triples if _keyword_in_triple(triple, keyword))
        weights[keyword] = math.log((n + 1) / (document_frequency + 1)) + 1
    return weights


def score_triple_weighted(triple: Dict[str, Any], weights: Dict[str, float]) -> float:
    """Like score_triple, but each keyword counts by its keyword_weights()
    weight instead of equally. See keyword_weights for why."""
    score = 0.0
    for field, field_weight in _FIELD_WEIGHTS:
        haystack = str(triple.get(field) or "").lower()
        if not haystack:
            continue
        for keyword, weight in weights.items():
            if _keyword_matches(keyword, haystack):
                score += field_weight * weight
    return score


def resolve_port(explicit_port: Optional[int]) -> int:
    """The port to serve on: an explicit --port always wins; otherwise a
    hosting platform's injected $PORT (Render, Railway, Fly.io all set
    this), falling back to 8000 if neither is set -- unchanged local
    development behaviour.
    """
    if explicit_port is not None:
        return explicit_port
    return int(os.environ.get("PORT", 8000))


def dedupe_triples(triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop duplicate facts -- same (subject, predicate, object) cited from
    several passages -- keeping the first (i.e. highest-ranked, if the
    caller already sorted) occurrence of each.
    """
    seen: Set[Tuple[Any, Any, Any]] = set()
    unique = []
    for triple in triples:
        key = (triple.get("subject"), triple.get("predicate"), triple.get("object"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(triple)
    return unique


# ============================================================================
# 1. Knowledge Graph Loader and Index
# ============================================================================

class KnowledgeGraph:
    """
    Loads a knowledge graph from a CSV file and builds an entity index for fast lookup.

    The CSV must contain columns: subject, predicate, object, sentence_ref, source_section, confidence.
    The index maps each entity (subject or object) to the list of triple indices where it appears.
    """

    def __init__(self, csv_path: str):
        # Load all triples and build the in‑memory index.
        paths = [csv_path] if isinstance(csv_path, (str, os.PathLike)) else list(csv_path)
        if not paths:
            raise ValueError("At least one CSV path is required.")
        self.triples = []
        seen_paths = set()
        for path in paths:
            resolved = Path(path).expanduser().resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            records = self._load_csv(str(resolved))
            for record in records:
                record["id"] = f"csv:{len(self.triples)}"
                self.triples.append(record)
        self._build_index()
        print(f"Loaded {len(self.triples)} triples")
        print(f"Entities indexed: {len(self.entity_index)} unique names")

    def _load_csv(self, path: str) -> List[Dict]:
        """Read the CSV and return a list of clean triple dictionaries."""
        triples = []
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                triple = {
                    # Stable enough for the CSV path's own lifetime (process-
                    # local, not persisted) so feedback can still reference
                    # "the triples actually used" the same way the Neo4j
                    # path's elementId(r) does. Unlike the graph path, a CSV
                    # triple can't currently be archived on a rejected-
                    # feedback review -- see auth_store.review_feedback.
                    'id': f"csv:{len(triples)}",
                    'subject': row.get('subject', '').strip(),
                    'predicate': row.get('predicate', '').strip(),
                    'object': row.get('object', '').strip(),
                    'sentence_ref': row.get('sentence_ref', '').strip(),
                    'source_section': row.get('source_section', 'Unknown'),
                    'confidence': row.get('confidence', 'Medium'),
                    'passage': row.get('passage', ''),
                    'time_period': row.get('time_period', '').strip(),
                    'question': row.get('question', '').strip(),
                    'evidence_kind': row.get('evidence_kind', '').strip(),
                    'record_id': row.get('record_id', '').strip(),
                    **provenance_fields(row)
                }
                # Keep only complete triples (all three main parts present).
                if triple['subject'] and triple['predicate'] and triple['object']:
                    triples.append(triple)
        return triples

    def _build_index(self) -> None:
        """
        Create an index: entity (lowercased) → list of triple indices.
        This makes retrieving triples by entity O(1) instead of scanning the whole list.
        """
        self.entity_index = defaultdict(lambda: [])
        self.all_entities = set()
        for idx, t in enumerate(self.triples):
            subj = t['subject'].lower()
            obj = t['object'].lower()
            self.entity_index[subj].append(idx)
            self.entity_index[obj].append(idx)
            self.all_entities.add(subj)
            self.all_entities.add(obj)

    def get_triple(self, idx: int) -> Dict:
        """Return the triple at a given index."""
        return self.triples[idx]

    def get_triples_by_entities(self, entities: Set[str]) -> List[Dict]:
        """
        Retrieve all triples that contain any of the given entities.
        Entities must be lowercased.
        """
        indices = set()
        for ent in entities:
            indices.update(self.entity_index.get(ent, []))
        return [self.triples[i] for i in indices]

    def get_all_entities(self) -> Set[str]:
        """Return the set of all entity names (lowercased)."""
        return self.all_entities

    def get_schema(self) -> str:
        """
        Generate a human‑readable schema description for use in LLM prompts.
        Only the first 20 predicates are shown to keep the prompt concise.
        """
        predicates = set(t['predicate'] for t in self.triples)
        pred_list = ', '.join(sorted(predicates)[:20])
        return f"""Knowledge Graph Schema:
- Entity types: Person, Organization, Location, Event, Artifact, Other
- Relationship types: {pred_list}...
- Each triple: (Subject)-[PREDICATE]->(Object)
- Source sentences are stored as sentence_ref
"""


# ============================================================================
# 2. Approach A: Cypher Translation (LLM‑based)
# ============================================================================

class CypherRetriever:
    """
    Retrieves triples by using an LLM to generate a pseudo‑Cypher query from the question.
    The query is then parsed to extract entity and predicate hints, which are used to filter the KG.

    This approach is more flexible for complex queries but requires a local LLM (Ollama)
    and is slower and less reliable than Concept Matching.
    """

    def __init__(self, kg: KnowledgeGraph, ollama_url: Optional[str] = None):
        self.kg = kg
        # Reads from the environment so this works correctly inside Docker, where
        # docker-compose.yml overrides OLLAMA_URL to point at the ollama service
        # rather than localhost. Falls back to localhost for native (non-Docker) runs.
        # resolve_llm_endpoint refuses a host outside our own network: this
        # project committed that paper content goes to a local model only.
        # Checked here so `rag.py --serve` fails at startup, not mid-query.
        self.ollama_url = resolve_llm_endpoint(
            ollama_url or os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
        )
        self.model = os.getenv("OLLAMA_MODEL", "deepseek-r1:7b")

    def _generate_cypher(self, question: str) -> str:
        """
        Send the question to the LLM and ask it to produce a Cypher‑like query.
        The expected format includes a CONTAINS clause for entities and a predicate label.
        """
        schema = self.kg.get_schema()
        prompt = f"""You are a knowledge graph query assistant. Convert the user question into a retrieval query.

Schema:
{schema}

Format: Return a simple list of entities and predicates to match.
Example question: "Where do the Garo people live?"
Example output: MATCH (s)-[r:LIVE_IN]->(o) WHERE s CONTAINS 'Garo' RETURN s, r, o

Question: {question}

Return only the query, no explanation."""
        try:
            resp = requests.post(
                self.ollama_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 2048}
                },
                timeout=60
            )
            if resp.status_code == 200:
                return resp.json().get("response", "")
        except Exception as e:
            print(f"Cypher generation error: {e}")
        return ""

    def _execute_cypher(self, cypher: str) -> List[Dict]:
        """
        Parse the generated Cypher string to extract entity and predicate hints,
        then filter the triples accordingly. This is a very simple parser – it does not
        actually run a full Cypher engine.
        """
        matches = []
        # Look for CONTAINS 'something' in the WHERE clause.
        entity_match = re.search(r"CONTAINS\s*['\"]([^'\"]+)['\"]", cypher, re.IGNORECASE)
        # Look for [r:PREDICATE] to get the predicate.
        pred_match = re.search(r"\[r:([^\]]+)\]", cypher, re.IGNORECASE)

        entity = entity_match.group(1).lower() if entity_match else None
        predicate = pred_match.group(1).upper() if pred_match else None

        for t in self.kg.triples:
            if entity and entity not in t['subject'].lower() and entity not in t['object'].lower():
                continue
            if predicate and predicate != t['predicate']:
                continue
            matches.append(t)
        return matches

    def retrieve(self, question: str, top_k: int = 10) -> List[Dict]:
        """Full pipeline: generate query, execute, return top‑k triples."""
        cypher = self._generate_cypher(question)
        if not cypher:
            return []
        matches = self._execute_cypher(cypher)
        return matches[:top_k]


# ============================================================================
# 3. Approach B: Concept Matching (with fallbacks)
# ============================================================================

class ConceptRetriever:
    """
    Retrieves triples by scoring every triple against the question's content
    words -- the same question_keywords/score_triple ranking
    Neo4jRAGSkeleton.query uses on the graph path.

    This approach is fast, deterministic, and does not require an LLM.
    It is the recommended primary retrieval strategy.
    """

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg

    def _extract_entities(self, question: str) -> Set[str]:
        """
        Find known entities from the KG that appear in the question as whole words.
        This avoids partial matches (e.g., 'Garo' should not match 'GaroWomen').
        Used by RetrieverComparator for its diagnostic entity count; retrieve()
        no longer needs it, since score_triple already rewards a subject/object
        match over one that merely appears in a source sentence.
        """
        question_lower = question.lower()
        entities = set()
        for entity in self.kg.get_all_entities():
            if re.search(r'\b' + re.escape(entity) + r'\b', question_lower):
                entities.add(entity)
        return entities

    def retrieve(self, question: str, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        """Scores every triple against the question's content words and
        returns the highest-ranked, deduped matches.

        Previously this had its own three-stage fallback (known-entity
        match, then predicate keyword match, then sentence_ref search) with
        its own scoring: 2 points per entity match, 1 per predicate keyword,
        plus a bonus for the LENGTH of sentence_ref ("longer = more
        context"). That rewarded verbose citations -- precisely the
        pathology MAX_SENTENCE_REF_CHARS exists to stop on the extraction
        side -- and ranked this CSV fallback differently from the graph
        path it is meant to stand in for. Scoring now goes through the same
        score_triple() the graph path uses, so a question gets the same
        answer whether or not AuraDB happens to be reachable.
        """
        keywords = question_keywords(question)
        if not keywords:
            return []

        # Weighted by keyword_weights so a rare, on-topic keyword outranks a
        # flat match on the graph's hub entity -- see keyword_weights.
        candidates = filter_community_periods(self.kg.triples, question)
        weights = keyword_weights(keywords, candidates)
        scored = [(score_triple_weighted(triple, weights), triple) for triple in candidates]
        # Stable sort on the negated score keeps the CSV's row order as the
        # tie-break, so equal-scoring results do not shuffle between calls.
        scored.sort(key=lambda pair: -pair[0])
        matches = [triple for score, triple in scored if score > 0]
        # In this corpus, community identity alone does not establish topic relevance.
        identity_terms = {"garo", "mandi", "mande", "people", "community"}
        topics = [word for word in keywords if word not in identity_terms]
        topic_forms = {
            "languages": ("language",),
            "speak": ("speaks", "speaking", "spoken", "bilingual", "language"),
        }

        def matches_topic(triple):
            fields = ("subject", "predicate", "object", "question", "sentence_ref")
            for word in topics:
                forms = (word,) + topic_forms.get(word, ())
                if any(
                    _keyword_matches(form, str(triple.get(field) or "").lower())
                    for form in forms
                    for field in fields
                ):
                    return True
            return False

        focused = [triple for triple in matches if matches_topic(triple)]
        if focused:
            matches = focused
        return group_responses(dedupe_triples(matches), top_k)


# ============================================================================
# 4. Evaluation and Comparison (with Data‑Driven Rationale)
# ============================================================================

class RetrieverComparator:
    """
    Runs both retrieval approaches on a set of test questions and produces a comparison summary.
    The comparison includes:
        - Total triples retrieved by each approach.
        - Overlap between the two result sets.
        - Per‑question statistics.
        - A data‑driven rationale that recommends the best approach based on the numbers.
    """

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg
        self.concept_retriever = ConceptRetriever(kg)
        self.cypher_retriever = CypherRetriever(kg)

    def compare(self, test_questions: List[str]) -> Dict:
        """
        Evaluate both retrievers on each test question and collect statistics.
        Returns a dictionary with full results and a per‑question comparison list.
        """
        results = {'concept': {}, 'cypher': {}, 'comparison': []}
        for i, q in enumerate(test_questions, 1):
            print(f"\n--- Question {i}: {q}")

            concept_triples = self.concept_retriever.retrieve(q, top_k=10)
            concept_entities = self.concept_retriever._extract_entities(q)
            cypher_triples = self.cypher_retriever.retrieve(q, top_k=10)

            results['concept'][q] = concept_triples
            results['cypher'][q] = cypher_triples

            concept_count = len(concept_triples)
            cypher_count = len(cypher_triples)
            # Compute overlap based on (subject, predicate, object) tuples.
            concept_set = set(tuple(sorted((t['subject'], t['predicate'], t['object']))) for t in concept_triples)
            cypher_set = set(tuple(sorted((t['subject'], t['predicate'], t['object']))) for t in cypher_triples)
            overlap = len(concept_set & cypher_set)

            print(f"  Concept: {concept_count} triples (entities found: {concept_entities})")
            print(f"  Cypher: {cypher_count} triples")
            print(f"  Overlap: {overlap} triples")
            if concept_triples:
                t = concept_triples[0]
                print(f"  Concept top: ({t['subject']})-[{t['predicate']}]->({t['object']})")
            if cypher_triples:
                t = cypher_triples[0]
                print(f"  Cypher top: ({t['subject']})-[{t['predicate']}]->({t['object']})")

            results['comparison'].append({
                'question': q,
                'concept_count': concept_count,
                'cypher_count': cypher_count,
                'overlap': overlap,
                'concept_entities': list(concept_entities)
            })
        return results

    def print_summary(self, results: Dict) -> None:
        """Print a summary of the comparison results."""
        print("\n" + "=" * 60)
        print("COMPARISON SUMMARY")
        print("=" * 60)
        total_concept = sum(r['concept_count'] for r in results['comparison'])
        total_cypher = sum(r['cypher_count'] for r in results['comparison'])
        total_overlap = sum(r['overlap'] for r in results['comparison'])
        print(f"Total triples retrieved:")
        print(f"  Concept matching: {total_concept}")
        print(f"  Cypher translation: {total_cypher}")
        print(f"  Overlap: {total_overlap}")
        print(f"  Concept unique: {total_concept - total_overlap}")
        print(f"  Cypher unique: {total_cypher - total_overlap}")
        print("\nPer-question detail:")
        for r in results['comparison']:
            print(f"  '{r['question'][:50]}...':")
            print(f"    Concept: {r['concept_count']} | Cypher: {r['cypher_count']} | Overlap: {r['overlap']}")
            if r['concept_entities']:
                print(f"    Entities found: {', '.join(r['concept_entities'])}")

    def print_rationale(self, results: Dict) -> None:
        """
        Print a data‑driven rationale for choosing the primary retrieval approach.
        Uses the comparison numbers to justify the decision, and outlines future improvements.
        """
        total_concept = sum(r['concept_count'] for r in results['comparison'])
        total_cypher = sum(r['cypher_count'] for r in results['comparison'])
        total_overlap = sum(r['overlap'] for r in results['comparison'])
        total_questions = len(results['comparison'])

        avg_concept = total_concept / total_questions if total_questions else 0
        avg_cypher = total_cypher / total_questions if total_questions else 0

        concept_nonzero = sum(1 for r in results['comparison'] if r['concept_count'] > 0)
        cypher_nonzero = sum(1 for r in results['comparison'] if r['cypher_count'] > 0)

        print("\n" + "=" * 70)
        print("DECISION RATIONALE (Data‑Driven)")
        print("=" * 70)

        print("\nQuantitative Summary:")
        print(f"  - Test questions evaluated: {total_questions}")
        print(f"  - Concept Matching retrieved {total_concept} triples total (avg {avg_concept:.1f} per question)")
        print(f"  - Cypher Translation retrieved {total_cypher} triples total (avg {avg_cypher:.1f} per question)")
        print(f"  - Both approaches agreed on {total_overlap} triples (overlap)")
        print(f"  - Concept Matching found at least one triple for {concept_nonzero}/{total_questions} questions")
        print(f"  - Cypher Translation found at least one triple for {cypher_nonzero}/{total_questions} questions")

        print("\nStrengths & Weaknesses:")
        print(f"  Concept Matching:")
        print(f"    + Retrieved {total_concept - total_cypher} more triples than Cypher Translation.")
        print(f"    + Had a non‑zero result for {concept_nonzero - cypher_nonzero} more questions.")
        print(f"    + No LLM call → fast and free.")
        print(f"    - Cannot handle complex multi‑hop queries (e.g., 'Who worked on projects led by NASA?').")
        print(f"  Cypher Translation:")
        print(f"    + Can theoretically handle complex relational queries.")
        print(f"    + Retrieved {total_cypher - total_overlap} triples that Concept Matching missed.")
        print(f"    - Requires a local LLM (Ollama) → slower and resource‑intensive.")
        print(f"    - Often failed to generate a valid query ({total_questions - cypher_nonzero} questions returned 0 triples).")

        print("\nDecision:")
        if total_concept >= total_cypher and concept_nonzero >= cypher_nonzero:
            print("  Select Concept Matching as the primary retrieval approach.")
            print(f"     It retrieved {total_concept - total_cypher} more triples overall and returned something for {concept_nonzero - cypher_nonzero} more questions.")
            print("     For the current KG (simple triples, single‑hop facts), this is the most reliable and efficient choice.")
        else:
            print("  Consider Cypher Translation if complex queries become frequent.")

        print("\nFuture Enhancement:")
        print("  - Keep Cypher Translation as an optional route for advanced queries (e.g., multi‑hop).")
        print("  - Add a hybrid mode: try Concept Matching first; if it returns < 3 triples, fall back to Cypher.")
        print("=" * 70)


# ============================================================================
# 5. Minimal Skeleton: Question → Retrieval → Triples
# ============================================================================

class RAGSkeleton:
    """
    Main entry point for the RAG retrieval layer.
    Wraps the chosen retriever (Concept or Cypher) and provides:
        - `query(question, top_k)` : returns a list of triples.
        - `format_output(triples)` : formats triples for human reading.

    This class is designed to be imported and used in other applications.
    """

    def __init__(self, kg_path: str, approach: str = "concept"):
        self.kg = KnowledgeGraph(kg_path)
        self.approach = approach
        if approach == "concept":
            self.retriever = ConceptRetriever(self.kg)
        elif approach == "cypher":
            self.retriever = CypherRetriever(self.kg)
        else:
            raise ValueError("approach must be 'concept' or 'cypher'")

    def normalize_question(self, question: str) -> str:
        """
        Optional: replace 'Garo' with 'Garo people' for respectful terminology.
        This helps match the KG if you have updated entities to 'Garo people'.
        Currently disabled by default – enable if needed by uncommenting the return.
        """
        # return re.sub(r'\bGaro\b', 'Garo people', question, flags=re.IGNORECASE)
        return question

    def query(self, question: str, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        """Main entry: question in → triples out."""
        normalized = self.normalize_question(question)
        return self.retriever.retrieve(normalized, top_k)

    def format_output(self, triples: List[Dict]) -> str:
        """
        Convert a list of triples into a human‑friendly text block.
        Includes the triple itself, the source sentence, and the page number (if available).
        """
        if not triples:
            return "No triples found. Try rephrasing your question or ask about a different topic."
        lines = []
        for t in triples:
            lines.append(f"({t['subject']}) -[{t['predicate']}]-> ({t['object']})")
            if t.get('sentence_ref'):
                lines.append(f"  // Source: {t['sentence_ref']}")
            if t.get('source_section'):
                lines.append(f"  // Page: {t['source_section']}")
            lines.append("")  # blank line between triples
        return "\n".join(lines)

    # Releases any resources held by the CSV-backed implementation.
    # This is a no-op for local file-based retrieval, but it matches the
    # shutdown contract used by the HTTP server.
    def close(self) -> None:
        pass


# Queries Entity nodes and their relationships directly from Neo4j.
class Neo4jRAGSkeleton:
    # Upper bound on rows pulled back for ranking. Well above the current
    # graph (45 triples) and above the ~350 expected after 20 more papers,
    # so it never truncates in practice -- it exists so an unexpectedly
    # large graph degrades instead of pulling everything into memory.
    FETCH_LIMIT = 500

    # Opens a Neo4j driver using the project's environment configuration.
    def __init__(self):
        from config import PASSWORD, URI, USERNAME

        if GraphDatabase is None:
            raise ImportError("The 'neo4j' package is required to use Neo4jRAGSkeleton. Install it with 'pip install neo4j'.")

        uri = str(URI or "")
        username = str(USERNAME or "")
        password = str(PASSWORD or "")

        if not uri or not username or not password:
            raise ValueError("Neo4j configuration is incomplete. Set URI, USERNAME, and PASSWORD in config or environment.")

        self.driver = GraphDatabase.driver(uri, auth=(username, password))

    # Finds graph relationships whose entities or source text match the question.
    def query(self, question: str, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        """Fetch every triple the question's words touch, then rank in Python.

        Ranking moved out of Cypher deliberately. The old query scored with
        `reduce` over a hardcoded relationship_terms list -- speak/language/
        dialect, population, live/locat/resid, is_a/type -- matched against
        the predicate NAME. The graph's predicates are LANGUAGE_USED,
        EXTENT_OF_USE, HAS_LANGUAGE_Maintenance, HAS_TRADITIONAL_RELIGION and
        so on; only POPULATION ever matched one, so 10 of 11 predicate types
        scored 0, ORDER BY relevance was a tie across nearly everything, and
        Neo4j's scan order chose the answer.

        Scoring here instead makes the ranking unit-testable without a live
        database, and lets a match on the subject or object outrank one that
        merely mentions the word in a source sentence.

        This is a full relationship scan with no index -- free at the current
        45 triples and fine into the low thousands, but it is the documented
        ceiling on this read path. FETCH_LIMIT bounds the worst case.
        """
        keywords = question_keywords(question)
        if not keywords:
            return []

        cypher = """
        MATCH (s:Entity)-[r]->(o:Entity)
        WHERE coalesce(r.archived, false) = false
          AND coalesce(s.archived, false) = false
          AND coalesce(o.archived, false) = false
          AND any(keyword IN $keywords WHERE
            toLower(coalesce(s.name, '')) CONTAINS keyword OR
            toLower(coalesce(o.name, '')) CONTAINS keyword OR
            toLower(type(r)) CONTAINS keyword OR
            toLower(coalesce(r.sentence_ref, '')) CONTAINS keyword OR
            toLower(coalesce(r.passage, '')) CONTAINS keyword)
        RETURN elementId(r) AS id,
               s.name AS subject,
               type(r) AS predicate,
               o.name AS object,
               coalesce(r.sentence_ref, '') AS sentence_ref,
               coalesce(r.source_section, '') AS source_section,
               coalesce(r.passage, '') AS passage,
               coalesce(r.paper_title, '') AS paper_title,
               coalesce(r.source_file, '') AS source_file,
               coalesce(r.page_number, '') AS page_number,
               coalesce(r.source_type, '') AS source_type,
               coalesce(r.confidence, '') AS confidence
        LIMIT $fetch_limit
        """

        with self.driver.session() as session:
            result = session.run(
                cypher,
                keywords=keywords,
                fetch_limit=self.FETCH_LIMIT,
            )
            candidates = [dict(record) for record in result]
            for candidate in candidates:
                candidate.update(provenance_fields(candidate))

        # Weighted by keyword_weights so a rare, on-topic keyword outranks a
        # flat match on the graph's hub entity -- see keyword_weights.
        # Stable sort on the negated score keeps Cypher's order as the
        # tie-break, so equal-scoring results do not shuffle between calls.
        weights = keyword_weights(keywords, candidates)
        candidates.sort(key=lambda triple: -score_triple_weighted(triple, weights))

        # Dedupe before truncating, so a duplicate doesn't cost a real
        # candidate its place in top_k. Sorting first means the
        # highest-scoring instance of each fact is the one kept.
        return dedupe_triples(candidates)[:top_k]

    # Formats Neo4j triples for the Flutter assistant response.
    def format_output(self, triples: List[Dict]) -> str:
        if not triples:
            return "No triples found. Try rephrasing your question or ask about a different topic."

        lines = []
        for triple in triples:
            lines.append(
                f"({triple['subject']}) -[{triple['predicate']}]-> ({triple['object']})"
            )
            if triple.get('sentence_ref'):
                lines.append(f"  // Source: {triple['sentence_ref']}")
            if triple.get('source_section'):
                lines.append(f"  // Page: {triple['source_section']}")
            lines.append('')
        return '\n'.join(lines)

    # Closes the Neo4j network resources when the API stops.
    def close(self) -> None:
        self.driver.close()

    # Converts retrieved graph evidence into a concise, grounded answer.
# Benchmarked on this machine's CPU Ollama: deepseek-r1:7b took 40.8s and
# mistral:7b took 40.3s for a real synthesis call. The old timeout=30 was
# below both, so every real answer timed out and silently fell back to the
# templated response -- a bug, not a deliberate tradeoff. 90s clears both
# with headroom for a slow first call, while still failing well short of
# mistral-small3.1's measured 151.3s if that model is ever selected (a
# different, deliberately slow, model choice).
#
# Raised to 130s 2026-10-07: 90s was still not enough for a genuinely COLD
# question (no matching prompt in llama.cpp's own prompt cache). Measured via
# Ollama's own timing log on the real hosted-demo tunnel path: prefill of the
# ~2460-token evidence prompt alone took ~62s at this CPU's ~40 tokens/sec
# prefill speed, before decoding even starts; decode then added another
# ~50-60s. A same-prompt retest looked like a fast 52.7s total, but that was
# a prompt-cache hit (cached n_tokens = 2459 of 2460) from the first,
# cancelled attempt -- not representative, since every real question has a
# different evidence prompt. See SYNTHESIS_EVIDENCE_LIMIT below, which
# attacks the actual bottleneck (prefill length) directly; this timeout is
# the safety margin on top of that fix, not a substitute for it.
ANSWER_SYNTHESIS_TIMEOUT_SECONDS = 130

# Caps how many retrieved triples go into the synthesis PROMPT (citations in
# the "View verified sources" panel still show all of DEFAULT_TOP_K=25 --
# this only shrinks what gets sent to the model). WHY: prefill time scales
# ~linearly with prompt length, and all 25 triples as JSON evidence produce a
# ~2460-token prompt that alone takes ~62s to prefill on this CPU (~40
# tokens/sec), which is most of the timeout budget before decoding even
# starts. Triples already arrive score-sorted, so keeping the top N keeps the
# most relevant evidence.
SYNTHESIS_EVIDENCE_LIMIT = 10

# How long to wait for Ollama to even ACCEPT a connection, separate from how
# long to wait for it to finish generating (above). This matters once the
# hosted demo architecture is live: the hosted API's OLLAMA_URL points at a
# Tailscale Funnel tunnel to a team laptop that is only turned on during the
# live demo. The rest of the time nothing is listening there, so every
# uncached question would otherwise make a real visitor wait the full 90s
# before falling back to the template. A short connect timeout fails fast
# when nothing is there, while still allowing the full 90s once a real
# connection is made and generation has actually started.
ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS = 10

# How many times to retry a request that failed to connect at all (not one
# that connected and then ran out of time generating -- see answer() for the
# distinction). WHY: live-tested 2026-10-07 against the real hosted tunnel
# with the laptop/Funnel genuinely up and every layer individually confirmed
# healthy (Ollama, the authenticating proxy, Funnel itself) -- one request in
# three still failed to connect at all in well under a second, while the
# next two identical requests succeeded with real generation. The proxy's own
# log showed no trace of the failed attempt ever arriving, so the drop is
# somewhere in the Render-to-Funnel network path itself, not in this code.
# One retry is enough to mask a single transient blip without materially
# changing the worst case: retrying a connection failure (fast) is cheap;
# retrying a full generation timeout would double a 130s wait, which is why
# this only catches ConnectionError, not the broader Timeout/RequestException
# that a slow-but-connected generation can raise.
ANSWER_SYNTHESIS_CONNECTION_RETRIES = 1

# Same spelling of "off" as llm_endpoint.py's ALLOW_EXTERNAL_LLM check,
# rather than a second convention in the same codebase. Defined here rather
# than imported because llm_endpoint._FALSEY is private to that module.
_FALSEY = {"", "0", "false", "no", "off"}


# The relevance gate makes the model declare on its first line whether the
# evidence actually answers the question, and rag.py discards everything
# after a "no" instead of trusting the model to stop writing (see
# _parse_gated_response). Defaults ON.
#
# SYNTHESIS_RELEVANCE_GATE=0 restores pre-2026-10-08 behaviour without a code
# change -- a rollback switch for the 2026-10-09 demo, settable from the
# Render dashboard. NOTE the "on" default below: os.getenv's fallback must
# not be "", which is itself in _FALSEY and would invert the default.
def relevance_gate_enabled() -> bool:
    return os.getenv("SYNTHESIS_RELEVANCE_GATE", "on").strip().lower() not in _FALSEY


# Shown when retrieval found nothing, and when the relevance gate judged that
# nothing retrieved actually answers the question. One constant so the two
# paths cannot drift into saying different things about the same situation.
NO_GROUNDED_ANSWER_MESSAGE = (
    "I could not find enough connected evidence to answer that question. "
    "Try naming a specific person, place, event, or relationship."
)

# Pre-computed answers for the demo's scripted questions (chat_page.dart's
# _examplePrompts). WHY: even after the timeout fix and the model switch
# above, measured 2026-10-05 showed real synthesis calls still taking 90s+
# on this machine -- 2x the ~40s benchmark from earlier sessions, cause not
# yet diagnosed -- and falling back to the templated answer when they
# exceeded even that ceiling. The scripted questions are known in advance,
# so their answers are precomputed once (see generate_demo_answer_cache.py)
# and served instantly and reliably from here; anything else still goes
# through live synthesis unchanged.
DEMO_ANSWER_CACHE_PATH = Path("data") / "demo_answer_cache.json"


def normalize_cache_key(question: str) -> str:
    """Collapses whitespace/case differences so a question matches its cache
    entry even if retyped, not just when sent verbatim by a suggested-prompt
    chip click."""
    return " ".join(question.strip().lower().split())


def load_demo_answer_cache(path: Path = DEMO_ANSWER_CACHE_PATH) -> Dict[str, str]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {normalize_cache_key(question): answer for question, answer in raw.items()}


# ============================================================================
# Answer languages
# ============================================================================

# Languages the Flutter app's LanguagePicker offers. The client sends the
# chosen code with each /query; the answer is written in that language.
# English stays the default so a client that sends no language (older app
# builds, curl, the CLI) behaves exactly as before.
DEFAULT_LANGUAGE = "en"
ANSWER_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "bn": "Bengali (Bangla)",
}

_NO_EVIDENCE_MESSAGES = {
    "en": "I could not find enough connected evidence to answer that question. Try naming a specific person, place, event, or relationship.",
    "hi": "इस सवाल का जवाब देने के लिए पर्याप्त जुड़े हुए प्रमाण नहीं मिले। किसी व्यक्ति, जगह, घटना या संबंध का नाम लेकर फिर से पूछें।",
    "bn": "এই প্রশ্নের উত্তর দেওয়ার মতো যথেষ্ট তথ্য পাওয়া যায়নি। কোনো নির্দিষ্ট ব্যক্তি, স্থান, ঘটনা বা সম্পর্কের নাম উল্লেখ করে আবার জিজ্ঞাসা করুন।",
}

# Shown above the English templated answer when the LLM is unreachable
# (e.g. the hosted demo with the tunnel off), since only the LLM can write
# the answer in another language.
_ENGLISH_ONLY_NOTES = {
    "hi": "(अभी हिंदी में अनुवाद उपलब्ध नहीं है, इसलिए उत्तर अंग्रेज़ी में दिखाया गया है।)",
    "bn": "(এই মুহূর্তে বাংলায় অনুবাদ করা যাচ্ছে না, তাই উত্তরটি ইংরেজিতে দেখানো হলো।)",
}

# Retrieval matches English keywords against an English graph, so a
# question typed in Bangla or Hindi would otherwise retrieve nothing. The
# LLM translates the question when it is reachable; this small glossary of
# the corpus's core terms keeps retrieval working when it is not. Matched as
# substrings, so inflected forms (e.g. গারোদের) still hit.
_RETRIEVAL_GLOSSARY = {
    # Bangla
    "গারো": "garo", "মান্দি": "mandi", "মান্দে": "mande", "আচিক": "achik",
    "ভাষা": "language", "উপভাষা": "dialect", "বাংলা": "bengali",
    "জনসংখ্যা": "population", "ধর্ম": "religion", "সংস্কৃতি": "culture",
    "সমস্যা": "challenge problem", "চ্যালেঞ্জ": "challenge",
    "বাস": "live reside", "থাকে": "live reside", "বসবাস": "live reside",
    "ঘর": "house housing", "বাড়ি": "house housing", "শিক্ষা": "education",
    "বাংলাদেশ": "bangladesh", "ভারত": "india", "মেঘালয়": "meghalaya",
    "টাঙ্গাইল": "tangail", "ময়মনসিংহ": "mymensingh", "মধুপুর": "madhupur",
    "নারী": "women", "সম্প্রদায়": "community",
    # Hindi
    "गारो": "garo", "भाषा": "language", "बोली": "dialect",
    "जनसंख्या": "population", "धर्म": "religion", "संस्कृति": "culture",
    "समस्या": "challenge problem", "चुनौती": "challenge", "चुनौति": "challenge",
    "रहते": "live reside", "घर": "house housing", "शिक्षा": "education",
    "बांग्लादेश": "bangladesh", "भारत": "india", "मेघालय": "meghalaya",
    "समुदाय": "community",
}


def normalize_language(code: Any) -> str:
    """Maps whatever the client sent to a supported language code."""
    lowered = str(code or "").strip().lower().replace("_", "-")
    base = lowered.split("-")[0]
    return base if base in ANSWER_LANGUAGES else DEFAULT_LANGUAGE


def glossary_keywords(question: str) -> str:
    """English search terms for the glossary words found in the question."""
    terms: List[str] = []
    for native, english in _RETRIEVAL_GLOSSARY.items():
        if native in (question or ""):
            for term in english.split():
                if term not in terms:
                    terms.append(term)
    return " ".join(terms)


def _is_plain_english(text: str) -> bool:
    """True when the question has no non-Latin letters to translate."""
    return not re.search(r"[^\x00-\x7F·]", text or "")


# How non-English questions and answers are translated.
#   auto (default): the free online services (Google, then MyMemory), and
#       only if both fail, a local Ollama model IF one happens to be running.
#       Nobody needs Ollama installed: without it that last step fails
#       instantly and the English answer is shown with a short note.
#   online (alias: google): Google, then MyMemory; never the local model.
#   llm: the local Ollama model only. Nothing leaves the machine, but it
#       needs the model installed and is much slower.
# Both online services are reached through the deep-translator library and
# need no API key. NOTE: the question and the answer text are sent to them
# -- see README "Languages". Google's free endpoint has no guarantee: it
# answered a single request with 429 Too Many Requests on a team laptop on
# 2026-10-08, which is why MyMemory backs it up.
TRANSLATION_PROVIDERS = {"local", "auto", "online", "google", "llm"}
_GOOGLE_MAX_CHARS = 4500  # Google's per-request limit is 5000.
# After Google refuses with 429, skip it for this long instead of paying a
# failed round trip on every question.
GOOGLE_COOLDOWN_SECONDS = 600
_google_blocked_until = 0.0

# Bangla/Hindi text costs the local model several tokens per character, so a
# translated answer needs far more tokens and time than an English one.
TRANSLATED_ANSWER_MAX_TOKENS = 1500
TRANSLATION_TIMEOUT_SECONDS = 240


def translation_provider() -> str:
    value = os.getenv("TRANSLATION_PROVIDER", "local").strip().lower()
    if value == "google":
        return "online"
    return value if value in TRANSLATION_PROVIDERS else "local"


# MyMemory: free, no key, but 500 characters per request and a daily
# character quota per IP (roughly 5,000/day anonymously, about 50,000/day
# when MYMEMORY_EMAIL is set to any real address).
_MYMEMORY_CODES = {"en": "en-GB", "bn": "bn-IN", "hi": "hi-IN"}
_MYMEMORY_MAX_CHARS = 480
MYMEMORY_COOLDOWN_SECONDS = 3600
MYMEMORY_TRANSIENT_COOLDOWN_SECONDS = 30
_mymemory_blocked_until = 0.0


def _split_for_limit(text: str, limit: int) -> List[str]:
    """Splits text into pieces under `limit` chars, at paragraph and then
    sentence boundaries where possible, so each request stays valid.
    A sentence that is still too long is cut between words, never inside a
    word: a half word sent to a translator comes back wrong or not at all."""
    pieces: List[str] = []
    for paragraph in [p for p in text.split("\n\n") if p.strip()]:
        if len(paragraph) <= limit:
            pieces.append(paragraph)
            continue
        current = ""
        for sentence in re.split(r"(?<=[.!?।])\s+", paragraph):
            while len(sentence) > limit:  # one very long sentence
                if current:
                    pieces.append(current)
                    current = ""
                cut = sentence.rfind(" ", 0, limit + 1)
                if cut <= 0:
                    cut = limit  # a single "word" longer than the limit
                pieces.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            if current and len(current) + 1 + len(sentence) > limit:
                pieces.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            pieces.append(current)
    return [piece for piece in pieces if piece]


# Spellings of the project's own names that the online translators get
# wrong or render inconsistently in Bangla. Applied to every English ->
# Bangla translation.
_BANGLA_SPELLING_FIXES = {
    "মান্ডি": "মান্দি", "মান্ডী": "মান্দি", "মান্দী": "মান্দি",
    "মান্ডে": "মান্দে",
    "এ·চিক": "আচিক", "আ·চিক": "আচিক", "এচিক": "আচিক", "আছিক": "আচিক",
    "গ্যারো": "গারো", "গারোস": "গারো",
    "ওয়াঙ্গালা": "ওয়ানগালা",
    # English terms written out in Bangla letters instead of translated.
    "ক্লাইমেট চেঞ্জের": "জলবায়ু পরিবর্তনের", "ক্লাইমেট চেঞ্জ": "জলবায়ু পরিবর্তন",
    "ইন্ডিজেনাস": "আদিবাসী", "ইন্ডিজেন": "আদিবাসী", "কমিউনিটির": "সম্প্রদায়ের",
    "কমিউনিটি": "সম্প্রদায়", "কালচারাল": "সাংস্কৃতিক", "কালচার": "সংস্কৃতি",
    "ট্র্যাডিশনাল": "ঐতিহ্যবাহী", "মেডিসিন": "ওষুধ", "ল্যাঙ্গুয়েজ": "ভাষা",
    "ইকোসিস্টেম": "বাস্তুতন্ত্র", "একসিস্টেম": "বাস্তুতন্ত্র",
}


def _prepare_for_translation(text: str) -> str:
    """The middle dot in A·chik makes translators split the name."""
    return (text or "").replace("·", "")


# Google writes "300,000" in Bangla as "৩০০, ০০০" -- a space after each
# thousands comma, which then reads (and is spoken) as separate numbers.
_SPACED_THOUSANDS = re.compile(r"(?<=[0-9০-৯]),\s+(?=[0-9০-৯]{3}(?![0-9০-৯]))")


_TO_BANGLA_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")

# Google writes "3 million" as "৩ মিলিয়ন" -- the English word in Bangla
# letters. Bangla counts large numbers in লাখ (100,000) and কোটি (10,000,000).
_BIG_UNITS = {"মিলিয়ন": 10 ** 6, "মিলিয়ন": 10 ** 6, "বিলিয়ন": 10 ** 9,
              "বিলিয়ন": 10 ** 9, "ট্রিলিয়ন": 10 ** 12, "ট্রিলিয়ন": 10 ** 12}
_BANGLA_WORD_NUMBERS = {"এক": 1, "দুই": 2, "তিন": 3, "চার": 4, "পাঁচ": 5,
                        "ছয়": 6, "সাত": 7, "আট": 8, "নয়": 9, "দশ": 10}
_BIG_NUMBER = re.compile(
    r"(?:([0-9০-৯]+(?:[.,][0-9০-৯]+)?|" + "|".join(_BANGLA_WORD_NUMBERS)
    + r")\s*)?(" + "|".join(_BIG_UNITS) + r")")
_FROM_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def _in_lakh_crore(total: int) -> str:
    parts = []
    for size, word in ((10 ** 7, "কোটি"), (10 ** 5, "লাখ"), (1000, "হাজার")):
        if total >= size:
            parts.append(f"{total // size} {word}")
            total %= size
    if total:
        parts.append(str(total))
    return " ".join(parts).translate(_TO_BANGLA_DIGITS)


def _big_number(match: "re.Match[str]") -> str:
    number, unit = match.group(1), match.group(2)
    value = 1.0
    if number in _BANGLA_WORD_NUMBERS:
        value = float(_BANGLA_WORD_NUMBERS[number])
    elif number:
        try:
            value = float(number.translate(_FROM_BANGLA_DIGITS).replace(",", ""))
        except ValueError:
            return match.group(0)
    return _in_lakh_crore(int(round(value * _BIG_UNITS[unit])))


def fix_bangla_spelling(text: str) -> str:
    for wrong, right in _BANGLA_SPELLING_FIXES.items():
        text = text.replace(wrong, right)
    text = _SPACED_THOUSANDS.sub(",", text)
    return _BIG_NUMBER.sub(_big_number, text)


def translation_incomplete(source: str, translated: str, target: str) -> bool:
    """True when a translation is empty, visibly shorter than its source, or
    mostly still in English -- the "skipped words" failure. Bangla and Hindi
    use roughly as many words as English, so under half is a dropped part."""
    if not (translated or "").strip():
        return True
    if target not in ("bn", "hi"):
        return False
    source_words = len(re.findall(r"[A-Za-z0-9]+", source or ""))
    translated_words = len(translated.split())
    if source_words >= 6 and translated_words < 0.5 * source_words:
        return True
    # Count words, not letters: Bangla vowel signs are not "letters" to
    # Python, which made one leftover English word look like half the text.
    words = re.findall(r"\w+", translated)
    latin = sum(1 for word in words if re.search(r"[A-Za-z]", word))
    return bool(words) and latin / len(words) > 0.4


def mymemory_translate(text: str, source: str, target: str) -> str:
    """Translates with MyMemory via deep-translator; "" if unavailable."""
    global _mymemory_blocked_until
    if not (text or "").strip() or time.time() < _mymemory_blocked_until:
        return ""
    source_code = _MYMEMORY_CODES.get(source)
    target_code = _MYMEMORY_CODES.get(target)
    if not source_code or not target_code:
        return ""  # MyMemory cannot auto-detect the source language
    try:
        from deep_translator import MyMemoryTranslator  # pyright: ignore[reportMissingImports]
    except ImportError:
        print("MyMemory translation unavailable: pip install deep-translator")
        return ""

    email = os.getenv("MYMEMORY_EMAIL") or None
    try:
        translator = MyMemoryTranslator(source=source_code, target=target_code, email=email)
        translated: List[str] = []
        for chunk in _split_for_limit(text, _MYMEMORY_MAX_CHARS):
            translation = translator.translate(chunk)
            if isinstance(translation, list):
                result = "".join(translation).strip()
            else:
                result = (translation or "").strip()
            # Out of quota is reported as a normal 200 with a warning
            # sentence in place of the translation.
            if "MYMEMORY WARNING" in result.upper():
                raise RuntimeError(result)
            if translation_incomplete(chunk, result, target):
                # MyMemory returns its closest stored match, which for
                # Bangla is often a shorter phrase with words missing.
                print("MyMemory returned an incomplete translation; not using it.")
                return ""
            translated.append(result)
    except Exception as error:
        message = str(error)
        quota_error = any(
            marker in message.lower()
            for marker in ("quota", "too many requests", "429", "mymemory warning")
        )
        cooldown = (
            MYMEMORY_COOLDOWN_SECONDS
            if quota_error
            else MYMEMORY_TRANSIENT_COOLDOWN_SECONDS
        )
        _mymemory_blocked_until = time.time() + cooldown
        print(f"MyMemory translation unavailable ({type(error).__name__}: "
              f"{message[:120]}); not retrying for "
              f"{cooldown} seconds.")
        return ""
    return "\n\n".join(part for part in translated if part)


# English words the translator sometimes leaves inside a Bangla or Hindi
# answer, often glued to the front of the translated word
# ("traditionalঐতিহ্যবাহী", "medicineষধ"). Known words are replaced from this
# list; anything else is translated on its own.
_LEFTOVER_ENGLISH = {
    "bn": {
        "garo": "গারো", "garos": "গারো", "mandi": "মান্দি", "mande": "মান্দে",
        "achik": "আচিক", "traditional": "ঐতিহ্যবাহী", "medicine": "ওষুধ",
        "medicines": "ওষুধ", "medicinal": "ঔষধি", "herbal": "ভেষজ",
        "practice": "চর্চা", "practices": "চর্চা", "community": "সম্প্রদায়",
        "culture": "সংস্কৃতি", "cultural": "সাংস্কৃতিক", "language": "ভাষা",
        "religion": "ধর্ম", "festival": "উৎসব", "matrilineal": "মাতৃতান্ত্রিক",
        "indigenous": "আদিবাসী", "research": "গবেষণা", "evidence": "প্রমাণ",
        "strong": "দৃঢ়", "identity": "পরিচয়", "heritage": "ঐতিহ্য",
        "climate": "জলবায়ু", "ecosystem": "বাস্তুতন্ত্র",
    },
    "hi": {
        "garo": "गारो", "mandi": "मांडी", "achik": "आचिक",
        "traditional": "पारंपरिक", "medicine": "दवा", "medicinal": "औषधीय",
        "practices": "प्रथाएँ", "community": "समुदाय", "culture": "संस्कृति",
    },
}
_SCRIPT_RANGES = {"bn": "\u0980-\u09FF", "hi": "\u0900-\u097F"}


def fill_leftover_english(text: str, target: str) -> str:
    """Translates English words left in a Bangla or Hindi translation."""
    script = _SCRIPT_RANGES.get(target)
    if not script or not re.search(r"[A-Za-z]", text or ""):
        return text
    # An English word, plus any target-script letters glued directly to it.
    token = re.compile(rf"[A-Za-z][A-Za-z'\-]*[{script}\u200c\u200d]*")
    known = _LEFTOVER_ENGLISH.get(target, {})
    replacements: Dict[str, str] = {}
    for match in token.finditer(text):
        word = re.match(r"[A-Za-z'\-]+", match.group(0)).group(0)
        key = word.lower()
        if key in replacements:
            continue
        if word.isupper() and len(word) <= 5:
            replacements[key] = ""  # acronyms such as DNA or NGO stay as they are
        elif key in known:
            replacements[key] = known[key]
        else:
            replacements[key] = google_translate(word, "en", target).strip()

    pieces: List[str] = []
    last = 0
    for match in token.finditer(text):
        whole = match.group(0)
        word = re.match(r"[A-Za-z'\-]+", whole).group(0)
        translated = replacements.get(word.lower(), "")
        before = text[last:match.start()]
        if translated and not re.search(r"[A-Za-z]", translated):
            # Glued Bangla after the English word is a broken copy of the same
            # word, and a short fragment just before it ("দৃ strong়" for
            # "দৃঢ়") is the start of it: both go.
            fragment = re.search(rf"(?:^|\s)([{script}]{{1,3}})\s$", before)
            if fragment and translated.startswith(fragment.group(1)):
                before = before[:fragment.start(1)]
            whole = translated
        pieces.append(before + whole)
        last = match.end()
    pieces.append(text[last:])
    return "".join(pieces)


_ANY_NUMBER = re.compile(r"[0-9০-৯]+(?:[.,]\s?[0-9০-৯]+)*")
# A number with the word after it, so "3 million" and "৩০ লাখ" are compared
# as whole amounts.
_SOURCE_AMOUNT = re.compile(
    r"([0-9]+(?:[.,][0-9]+)*)(?:\s*(thousand|lakh|lakhs|million|crore|crores|billion)\b)?",
    re.IGNORECASE)
_TRANSLATED_AMOUNT = re.compile(
    r"([0-9০-৯]+(?:[.,]\s?[0-9০-৯]+)*)(?:\s*(হাজার|লাখ|লক্ষ|কোটি|मिलियन|हज़ार|हजार|लाख|करोड़))?")
_UNIT_VALUES = {
    "thousand": 10 ** 3, "lakh": 10 ** 5, "lakhs": 10 ** 5, "million": 10 ** 6,
    "crore": 10 ** 7, "crores": 10 ** 7, "billion": 10 ** 9,
    "হাজার": 10 ** 3, "লাখ": 10 ** 5, "লক্ষ": 10 ** 5, "কোটি": 10 ** 7,
    "हज़ार": 10 ** 3, "हजार": 10 ** 3, "लाख": 10 ** 5, "करोड़": 10 ** 7,
    "मिलियन": 10 ** 6,
}
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def _amount(number: str, unit: Optional[str]) -> Optional[float]:
    digits = number.translate(_FROM_BANGLA_DIGITS).translate(_DEVANAGARI_DIGITS)
    digits = re.sub(r",\s?", "", digits)
    try:
        value = float(digits)
    except ValueError:
        return None
    return value * _UNIT_VALUES.get((unit or "").lower(), 1)


def restore_numbers(source: str, translated: str, target: str) -> str:
    """Puts the English answer's amounts back into the translation.

    Google sometimes regroups or pads numbers ("3000000" came back as
    "৩০০, ০০০, ০০০", ten times larger). When both texts contain the same
    count of numbers, each translated amount (number plus any unit word, so
    "৩০ লাখ") is compared with the English one in order; a wrong amount is
    replaced by the exact source value, in Bangla digits for Bangla, and in
    লাখ/কোটি when the English used a unit word ("3 million" -> "৩০ লাখ")."""
    sources = list(_SOURCE_AMOUNT.finditer(source or ""))
    translated_matches = list(_TRANSLATED_AMOUNT.finditer(translated or ""))
    if not sources or len(sources) != len(translated_matches):
        return translated
    pieces: List[str] = []
    last = 0
    for src, tr in zip(sources, translated_matches):
        wanted = _amount(src.group(1), src.group(2))
        shown = _amount(tr.group(1), tr.group(2))
        if wanted is None or shown == wanted:
            replacement = tr.group(0)  # already right; keep its wording
        elif src.group(2) and target == "bn" and float(wanted).is_integer():
            replacement = _in_lakh_crore(int(wanted))
        else:
            value = src.group(1).replace(" ", "")
            replacement = value.translate(_TO_BANGLA_DIGITS) if target == "bn" else value
            if src.group(2) and tr.group(2) is None:
                replacement += " " + src.group(2)
        pieces.append(translated[last:tr.start()] + replacement)
        last = tr.end()
    pieces.append(translated[last:])
    return "".join(pieces)


_SENTENCE_END = {"bn": r"(?<=[।.!?])\s+", "hi": r"(?<=[।.!?])\s+"}


def retranslate_mixed_sentences(source: str, translated: str, target: str) -> str:
    """Re-translates, one at a time, translated sentences that still contain
    English (e.g. "দৃ strong় ধারণা"). A sentence on its own almost always comes
    back clean. Needs the same number of sentences in source and translation
    so each one can be matched to its English original."""
    if target not in _SENTENCE_END or not re.search(r"[A-Za-z]{2,}", translated or ""):
        return translated
    out_paragraphs = []
    source_paragraphs = [p for p in (source or "").split("\n\n") if p.strip()]
    translated_paragraphs = [p for p in translated.split("\n\n") if p.strip()]
    if len(source_paragraphs) != len(translated_paragraphs):
        return translated
    for src_paragraph, tr_paragraph in zip(source_paragraphs, translated_paragraphs):
        src_sentences = [x for x in re.split(r"(?<=[.!?])\s+", src_paragraph.strip()) if x]
        tr_sentences = [x for x in re.split(_SENTENCE_END[target], tr_paragraph.strip()) if x]
        if len(src_sentences) != len(tr_sentences):
            out_paragraphs.append(tr_paragraph)
            continue
        fixed = []
        for src_sentence, tr_sentence in zip(src_sentences, tr_sentences):
            if re.search(r"[a-z]{2,}", tr_sentence):
                again = google_translate(src_sentence, "en", target).strip()
                if again and not re.search(r"[a-z]{2,}", again):
                    tr_sentence = again
            fixed.append(tr_sentence)
        out_paragraphs.append(" ".join(fixed))
    return "\n\n".join(out_paragraphs)


def online_translate(text: str, source: str, target: str) -> str:
    """Google first, then MyMemory. "" if neither could translate."""
    text = _prepare_for_translation(text)
    for service, translate in (("Google Translate", google_translate),
                               ("MyMemory", mymemory_translate)):
        translated = translate(text, source, target)
        if translated:
            print(f"Translated {source} -> {target} with {service}")
            if source == "en":
                translated = retranslate_mixed_sentences(text, translated, target)
            translated = fill_leftover_english(translated, target)
            if source == "en":
                translated = restore_numbers(text, translated, target)
            return fix_bangla_spelling(translated) if target == "bn" else translated
    return ""


class TranslationUnavailableError(RuntimeError):
    """Raised when the requested answer language could not be produced."""

    def __init__(self, language: str):
        self.language = language
        super().__init__(f"Translation to {language} is currently unavailable.")


def google_translate(text: str, source: str, target: str) -> str:
    """Translates with deep-translator; returns "" if it is unavailable."""
    global _google_blocked_until
    if not (text or "").strip():
        return ""
    if time.time() < _google_blocked_until:
        return ""
    try:
        from deep_translator import GoogleTranslator  # pyright: ignore[reportMissingImports]
    except ImportError:
        print("Google translation unavailable: pip install deep-translator")
        return ""

    chunks = _split_for_limit(text, _GOOGLE_MAX_CHARS)
    try:
        translator = GoogleTranslator(source=source, target=target)
        translated = []
        for chunk in chunks:
            result = (translator.translate(chunk[:_GOOGLE_MAX_CHARS]) or "").strip()
            if translation_incomplete(chunk, result, target):
                # Long paragraphs sometimes come back with sentences missing;
                # translating them one sentence at a time does not.
                sentences = [x for x in re.split(r"(?<=[.!?।])\s+", chunk) if x.strip()]
                result = " ".join(
                    (translator.translate(sentence) or "").strip() for sentence in sentences
                ).strip()
                if translation_incomplete(chunk, result, target):
                    print("Google returned an incomplete translation; not using it.")
                    return ""
            translated.append(result)
    except Exception as error:  # network errors, rate limits, bad responses
        if type(error).__name__ == "TooManyRequests":
            _google_blocked_until = time.time() + GOOGLE_COOLDOWN_SECONDS
            print(f"Google translation refused (429 Too Many Requests); "
                  f"not retrying for {GOOGLE_COOLDOWN_SECONDS // 60} minutes.")
        else:
            print(f"Google translation unavailable: {error}")
        return ""
    return "\n\n".join(part for part in translated if part)


class AnswerSynthesizer:
    SUPPORTED_LANGUAGES: Dict[str, str] = {
        "en": "English",
        "hi": "Hindi",
        "bn": "Bangla",
    }

    def __init__(
        self,
        ollama_url: Optional[str] = None,
        model: Optional[str] = None,
        answer_cache: Optional[Dict[str, str]] = None,
    ):
        self.ollama_url = ollama_url or os.getenv(
            "OLLAMA_URL", "http://localhost:11434/api/generate"
        )
        # mistral:7b, not deepseek-r1:7b: both benchmarked around 40s, but
        # deepseek-r1 is a "thinking" model whose internal reasoning length
        # (stripped by _clean_response's <think> regex) varies the actual
        # wall-clock time unpredictably. Measured 2026-10-05: 2 of 3 real
        # deepseek-r1 calls exceeded even the 90s ANSWER_SYNTHESIS_TIMEOUT
        # and fell back to the template, including one live chat request.
        # mistral:7b has no reasoning-token overhead to vary.
        self.model = model or os.getenv("OLLAMA_MODEL", "mistral:7b")
        self.answer_cache = load_demo_answer_cache() if answer_cache is None else answer_cache
        self.translation_cache: Dict[Tuple[str, str, str], str] = {}

    def translate_question(self, question: str, language: str) -> str:
        language = normalize_language(language)
        if language not in self.SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language}")
        if language == "en" or _is_plain_english(question):
            return question

        if translation_provider() == "local":
            from local_translation import translate_local
            return translate_local(question, language, "en") or question

        if translation_provider() != "llm":
            translated = online_translate(question, language, "en")
            if translated:
                return translated
            if translation_provider() == "online":
                return question

        return self._llm_translate(
            question,
            f"Translate this question from {self.SUPPORTED_LANGUAGES[language]} into English.",
            256,
            20,
            "Question translation",
        ) or question

    def english_question(self, question: str, language: str = DEFAULT_LANGUAGE) -> str:
        if normalize_language(language) == DEFAULT_LANGUAGE or _is_plain_english(question):
            return question
        translated = self.translate_question(question, language)
        return translated if translated != question else ""

    def question_for_retrieval(
        self,
        question: str,
        language: str = DEFAULT_LANGUAGE,
        translated: Optional[str] = None,
    ) -> str:
        language = normalize_language(language)
        if language == DEFAULT_LANGUAGE or _is_plain_english(question):
            return question

        english = (translated or self.english_question(question, language)).strip()
        glossary = glossary_keywords(question)
        if english == question and glossary:
            return f"{question} {glossary}"
        if glossary and glossary not in english.lower():
            return f"{english} {glossary}"
        return english

    def _llm_translate(
        self,
        text: str,
        instruction: str,
        max_tokens: int,
        timeout: Union[int, Tuple[int, int]],
        operation: str,
    ) -> str:
        prompt = f"""{instruction}
Return only the translation. Preserve names of people, places, and communities.

Text:
{text}

Translation:"""
        try:
            response = requests.post(
                self.ollama_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": max_tokens},
                },
                headers=ollama_tunnel_headers(),
                timeout=timeout,
            )
            if response.status_code == 200:
                translated = response.json().get("response", "").strip()
                if translated:
                    return self._clean_response(translated)
            else:
                print(f"{operation} unavailable: Ollama returned HTTP {response.status_code}")
        except (requests.RequestException, ValueError, KeyError) as error:
            print(f"{operation} unavailable: {error}")
        return ""

    def translate_answer(self, answer: str, language: str) -> str:
        language = normalize_language(language)
        if language == DEFAULT_LANGUAGE:
            return answer
        cache_key = (answer, DEFAULT_LANGUAGE, language)
        if cache_key in self.translation_cache:
            return self.translation_cache[cache_key]

        translated = ""
        provider = translation_provider()
        if provider == "local":
            from local_translation import translate_local
            translated = translate_local(answer, DEFAULT_LANGUAGE, language)
        elif provider != "llm":
            translated = online_translate(answer, DEFAULT_LANGUAGE, language)
        # The local model (mistral:7b) writes Bangla and Hindi with frequent
        # spelling errors, so in auto mode a failed online translation shows
        # the English answer with a note instead. TRANSLATION_PROVIDER=llm
        # still uses the local model on purpose.
        if not translated and provider == "llm":
            translated = self._llm_translate(
                answer,
                f"Translate the following text from English into "
                f"{self.SUPPORTED_LANGUAGES[language]}.",
                TRANSLATED_ANSWER_MAX_TOKENS,
                (
                    ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS,
                    TRANSLATION_TIMEOUT_SECONDS,
                ),
                "Answer translation",
            )
        if translated and language == "bn":
            translated = fix_bangla_spelling(translated)
        if translated:
            self.translation_cache[cache_key] = translated
        return translated

    def answer_translations(
        self,
        question: str,
        triples: List[Dict[str, Any]],
        english_question: Optional[str] = None,
        selected_language: str = DEFAULT_LANGUAGE,
    ) -> Dict[str, str]:
        selected_language = normalize_language(selected_language)
        english_question = english_question or self.english_question(question, "en")
        english_answer = self.answer(english_question, triples, "en")
        translations = {"en": english_answer}

        def translate(language: str) -> Tuple[str, str]:
            result = self.translate_answer(english_answer, language)
            return language, result or (
                f"{_ENGLISH_ONLY_NOTES[language]} {english_answer}"
            )

        languages = ("hi", "bn")
        selected_translation = None
        if selected_language in languages:
            target, selected_translation = translate(selected_language)
            if not selected_translation or selected_translation.startswith(
                _ENGLISH_ONLY_NOTES[selected_language]
            ):
                raise TranslationUnavailableError(selected_language)
            translations[target] = selected_translation
            languages = tuple(language for language in languages if language != target)

        if translation_provider() in {"online", "auto"}:
            with ThreadPoolExecutor(max_workers=2) as executor:
                for language, result in executor.map(translate, languages):
                    translations[language] = result
        else:
            for language in languages:
                target, result = translate(language)
                translations[target] = result
        return translations

    # Writes a natural-language answer while keeping every claim tied to evidence.
    def answer(
        self,
        question: str,
        triples: List[Dict[str, Any]],
        language: str = DEFAULT_LANGUAGE,
        english_question: Optional[str] = None,
    ) -> str:
        language = normalize_language(language)
        english_question = english_question or (
            question if language == DEFAULT_LANGUAGE
            else self.english_question(question, language)
        )
        if language != DEFAULT_LANGUAGE:
            if not triples:
                return _NO_EVIDENCE_MESSAGES[language]
            english_answer = self.answer(english_question, triples, DEFAULT_LANGUAGE)
            translated = self.translate_answer(english_answer, language)
            return translated or f"{_ENGLISH_ONLY_NOTES[language]} {english_answer}"

        if not triples:
            return self._no_evidence_message(DEFAULT_LANGUAGE)

        # Keep differing survey responses intact before cache or LLM rewriting.
        source_answer = source_response_answer(triples[:SYNTHESIS_EVIDENCE_LIMIT])
        if source_answer is not None:
            return source_answer

        cached = self.answer_cache.get(normalize_cache_key(english_question))
        if cached:
            return cached

        prompt = self._build_prompt(english_question, triples[:SYNTHESIS_EVIDENCE_LIMIT])
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 400,
                # 4096, not Ollama's default 2048. num_ctx covers prompt AND
                # generation: measured on the 16-triple demo CSV the evidence
                # prompt alone is ~1888 tokens, and num_predict reserves 400
                # more -- 2288 against a 2048 window. Ollama does not error on
                # that, it silently truncates the prompt from the LEFT, which
                # drops the system instructions and part of the question. That
                # is why the same question could return different answers.
                # The production graph, with more triples and longer
                # sentence_ref values, overruns further.
                "num_ctx": 4096,
            },
        }
        # Retries only a bare connection failure (see ANSWER_SYNTHESIS_CONNECTION_RETRIES
        # for why), never a slow-but-connected generation that ran out of time.
        for attempt in range(ANSWER_SYNTHESIS_CONNECTION_RETRIES + 1):
            try:
                response = requests.post(
                    self.ollama_url,
                    json=payload,
                    headers=ollama_tunnel_headers(),
                    timeout=(ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS, ANSWER_SYNTHESIS_TIMEOUT_SECONDS),
                )
            except requests.ConnectionError as error:
                print(f"Answer synthesis connection failed (attempt {attempt + 1}): {error}")
                continue
            except (requests.RequestException, ValueError, KeyError) as error:
                print(f"Answer synthesis unavailable: {error}")
                break
            else:
                # A non-200 (404 missing model, 500 server error, 400 bad
                # request) used to fall through to the templated fallback in
                # silence, making a broken synthesis path look exactly like a
                # working one from the outside. Say what happened.
                if response.status_code != 200:
                    print(
                        f"Answer synthesis returned HTTP {response.status_code}: "
                        f"{response.text[:300]}"
                    )
                if response.status_code == 200:
                    text = response.json().get("response", "").strip()
                    if not text:
                        print("Answer synthesis returned an empty response body.")
                    if text:
                        if not relevance_gate_enabled():
                            return self._clean_response(text)
                        verdict, gated = self._parse_gated_verdict(text)
                        # OLLAMA_MODEL is env-overridable; swap in a model
                        # that does not honour the RELEVANT: format and every
                        # answer silently becomes a refusal. Print which
                        # branch fired so an explicit "no" is distinguishable
                        # from format collapse mid-demo.
                        if verdict == self._GATE_NO:
                            print("Answer synthesis gate refused: the model judged the evidence irrelevant (RELEVANT: no).")
                        elif verdict == self._GATE_UNREADABLE:
                            print("Answer synthesis gate refused: the RELEVANT marker was missing or unreadable in the model's response.")
                        # A refusal is the intended output, not a failure:
                        # deliberately NOT _fallback_answer, whose templated
                        # triple soup is the off-topic padding being removed.
                        return gated if gated is not None else NO_GROUNDED_ANSWER_MESSAGE
                break

        return self._fallback_answer(triples, DEFAULT_LANGUAGE)

    # Builds a small evidence-only prompt for the local language model.
    def _build_prompt(self, question: str, triples: List[Dict[str, Any]], language: str = DEFAULT_LANGUAGE) -> str:
        language = normalize_language(language)
        from prompt_evidence import build_prompt_evidence
        evidence = build_prompt_evidence(triples)

        # Asking for a bounded first-line verdict, then enforcing the
        # consequence in code, is the part that differs from the two
        # prompt-only attempts reverted on 2026-10-07 -- both asked the model
        # to self-regulate its prose and it simply did not.
        gate_instruction = """Before answering, judge whether the evidence below directly answers the question.
Your FIRST line must be exactly one of:
RELEVANT: yes
RELEVANT: no
Write "no" if the evidence only touches the topic indirectly, mentions a
related word, or would require you to infer a connection the evidence does
not itself state. If "no", write nothing after that line.
If "yes", write the answer below it, using only evidence that directly
supports it.

""" if relevance_gate_enabled() else ""

        return f"""You are a careful knowledge-graph research assistant.
Answer the user's question using only the evidence below.
For community_data evidence, attribute each finding to its source_title (for
example, Community record 01). These are participant reports, not independently
verified facts or statements about the whole Mandi/Garo community.
Preserve negative answers such as No or None in the context of their question.
If records differ, describe the differing reports with source titles. Do not
invent a consensus or treat missing records as agreement. State that findings
refer to the retrieved records, not every group. Do not add causal explanations
unless the supplied response explicitly states them.
Some evidence entries group several facts under one shared source quotation.
Consider every relevant fact in each group; do not repeat its quotation for each fact.
Write the entire answer in {ANSWER_LANGUAGES.get(language, ANSWER_LANGUAGES[DEFAULT_LANGUAGE])}, regardless of the language used in the question.
Keep entity names and graph identifiers clear, but explain them in {ANSWER_LANGUAGES.get(language, ANSWER_LANGUAGES[DEFAULT_LANGUAGE])}.
The Mandi people are the same community as the Garo people (they call themselves
A·chik Mande), so treat "Mandi", "Mande", "A·chik" and "Garo" as the same people.
Do not invent facts, names, dates, or explanations that are not supported.
    Answer ONLY the question asked. Use evidence that directly answers it; ignore
    evidence about other topics even if it is about the same subject -- a question
    about health status should not discuss language, location, or unrelated challenges.
    Do not restate background facts (where they live, what they are also called)
    unless the question asks for them.
    If the question asks what an entity is, begin with a direct definition and then add
    one or two supported details such as location, language, or community identity.
    Translate graph identifiers such as GaroCommunity into natural language such as
    "the Garo community". Write 1-2 short sentences for a simple factual question; use
    more only if the question genuinely requires several distinct facts. Do not mention
    prompts, models, retrieval, graph triples, or page numbers.
    Only add a sentence about incomplete evidence if the evidence truly does not answer
    the question. If it does answer the question, answer it plainly and stop -- do not
    add a closing disclaimer out of habit.
{self._language_instruction(language)}
{gate_instruction}User question:
{question}

Evidence:
{json.dumps(evidence, ensure_ascii=False, indent=2)}

Answer:"""

    # The evidence is English; this tells the model which language to answer in.
    def _language_instruction(self, language: str) -> str:
        language = normalize_language(language)
        if language == DEFAULT_LANGUAGE:
            return ""
        name = ANSWER_LANGUAGES[language]
        return (
            f"Write the whole answer in {name}, even though the evidence is in English.\n"
            "Keep proper names (Garo, Mandi, A·chik, place names) recognisable, "
            "transliterated into the answer's script where natural.\n"
        )

    # Removes model-style prefixes that do not belong in the chat response.
    def _clean_response(self, text: str) -> str:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"^\s*(answer|response|translation)\s*:\s*", "", text, flags=re.IGNORECASE)
        return text.strip()

    # _parse_gated_verdict's three possible verdicts. GATE_NO is an explicit
    # "RELEVANT: no"; GATE_UNREADABLE covers everything else that fails
    # closed (missing marker, unrecognised value, or a "yes" with no answer
    # body) -- answer() logs the two differently so a genuine refusal is
    # distinguishable from the model's output format collapsing.
    _GATE_YES = "yes"
    _GATE_NO = "no"
    _GATE_UNREADABLE = "unreadable"

    # Reads the RELEVANT: yes/no marker the gate instruction asks for.
    # Returns (verdict, answer): answer is non-None only when verdict is
    # _GATE_YES. An unparseable response is not evidence that the answer is
    # grounded, and this project prefers an honest refusal to a confident
    # wrong one. See docs/superpowers/specs/2026-10-08-synthesis-relevance-gate-design.md
    #
    # _clean_response runs FIRST, and that order is load-bearing: deepseek-r1
    # emits <think>...</think> before anything else, and _clean_response also
    # strips a leading "Answer:" prefix, so "Answer: RELEVANT: yes" still
    # leaves the marker on line one.
    def _parse_gated_verdict(self, text: str) -> Tuple[str, Optional[str]]:
        cleaned = self._clean_response(text)
        lines = [line for line in cleaned.splitlines() if line.strip()]
        if not lines:
            return self._GATE_UNREADABLE, None

        # Models habitually decorate the marker -- "**RELEVANT: yes**", a
        # backticked marker, a marker inside a code fence -- and the bare
        # regex matched none of them. That is a FALSE refusal: the marker is
        # present, just dressed up, and refusing it costs recall for no
        # precision. Stripped from the MARKER LINE ONLY, so markdown inside
        # the answer body (lines 2+) survives untouched.
        #
        # Deliberately still lines[0] and not a scan of the first few lines:
        # tolerating a preamble before the marker widens what passes the
        # gate, which is a different tradeoff and not one taken here.
        marker_line = re.sub(r"[*`_#]+", "", lines[0])

        # [.:,;-]? consumes a single trailing punctuation mark after yes/no
        # (a model writing "RELEVANT: yes," must not leak a stray leading
        # comma -- and the meta-commentary after it -- into the answer).
        match = re.match(r"\s*RELEVANT\s*:\s*(yes|no)\b[.:,;-]?\s*", marker_line, flags=re.IGNORECASE)
        if not match:
            return self._GATE_UNREADABLE, None
        if match.group(1).lower() == "no":
            return self._GATE_NO, None

        # Keep anything trailing the marker on its own line: a model that
        # writes "RELEVANT: yes The Garo..." has still answered, and dropping
        # it would be a false refusal.
        head = marker_line[match.end():].strip()
        tail = "\n".join(lines[1:]).strip()
        remainder = "\n".join(part for part in (head, tail) if part).strip()
        if not remainder:
            return self._GATE_UNREADABLE, None
        return self._GATE_YES, remainder

    # Thin wrapper over _parse_gated_verdict for callers that only care
    # about None (refuse) vs the answer prose -- unchanged contract.
    def _parse_gated_response(self, text: str) -> Optional[str]:
        _, answer = self._parse_gated_verdict(text)
        return answer

    # Produces a readable answer when Ollama is offline or unavailable.
    def _fallback_answer(
        self,
        triples: List[Dict[str, Any]],
        language: str = DEFAULT_LANGUAGE,
    ) -> str:
        statements = [self._format_triple(triple, language) for triple in triples[:6]]
        statements = [statement for statement in statements if statement]
        if not statements:
            return self._no_evidence_message(language)
        introductions = {
            "en": "Based on the available knowledge, ",
            "es": "Según la información disponible, ",
            "fr": "D’après les informations disponibles, ",
            "hi": "उपलब्ध जानकारी के आधार पर, ",
            "zh": "根据现有信息，",
        }
        return introductions.get(language, introductions[DEFAULT_LANGUAGE]) + " ".join(statements)

    def _no_evidence_message(self, language: str) -> str:
        messages = {
            "en": "I could not find enough connected evidence to answer that question. Try naming a specific person, place, event, or relationship.",
            "es": "No encontré suficiente evidencia relacionada para responder. Intenta mencionar una persona, un lugar, un evento o una relación específica.",
            "fr": "Je n’ai pas trouvé suffisamment d’informations liées pour répondre. Essayez de nommer une personne, un lieu, un événement ou une relation précise.",
            "hi": "इस प्रश्न का उत्तर देने के लिए पर्याप्त जुड़ी हुई जानकारी नहीं मिली। किसी व्यक्ति, स्थान, घटना या संबंध का नाम लेकर पूछें।",
            "zh": "没有找到足够相关的信息来回答这个问题。请尝试指出具体的人物、地点、事件或关系。",
        }
        return messages[language]

    # Converts one graph triple into a readable, grounded sentence.
    def _format_triple(
        self,
        triple: Dict[str, Any],
        language: str = DEFAULT_LANGUAGE,
    ) -> str:
        subject = self._humanize_entity(triple.get("subject", "This entity"), language)
        raw_predicate = str(triple.get("predicate", ""))
        predicate_key = raw_predicate.upper().replace(" ", "_")
        # as_subject=False: a bare "Garo" as an OBJECT usually names the
        # language (e.g. LANGUAGE_USED's "GaroCommunity -> Garo"), not the
        # people -- see _humanize_entity for the bug this avoids.
        obj = self._humanize_entity(triple.get("object", "another entity"), language, as_subject=False)

        if language != DEFAULT_LANGUAGE:
            # Only a small, hand-translated subset of predicates has localized
            # templates -- this path is reached rarely (Ollama unreachable),
            # and the full corrected 32-predicate set below is English-only;
            # anything outside this subset falls through to the generic
            # localized-relation phrasing just below.
            translated_templates = {
                "es": {
                    "IS_A": f"{subject} es {obj}",
                    "TYPE": f"{subject} es {obj}",
                    "LOCATED_IN": f"{subject} se encuentra en {obj}",
                    "LIVE_IN": f"{subject} vive en {obj}",
                    "SPEAK_LANGUAGE": f"{subject} habla {obj}",
                    "BELONG_TO": f"{subject} pertenece a {obj}",
                    "HAS_LANGUAGE": f"{subject} usa el idioma {obj}",
                    "HAS_A_POPULATION": f"{subject} tiene una población estimada de {obj}",
                },
                "fr": {
                    "IS_A": f"{subject} est {obj}",
                    "TYPE": f"{subject} est {obj}",
                    "LOCATED_IN": f"{subject} se trouve à {obj}",
                    "LIVE_IN": f"{subject} vit à {obj}",
                    "SPEAK_LANGUAGE": f"{subject} parle {obj}",
                    "BELONG_TO": f"{subject} appartient à {obj}",
                    "HAS_LANGUAGE": f"{subject} utilise la langue {obj}",
                    "HAS_A_POPULATION": f"{subject} a une population estimée à {obj}",
                },
                "hi": {
                    "IS_A": f"{subject} {obj} है",
                    "TYPE": f"{subject} {obj} है",
                    "LOCATED_IN": f"{subject} {obj} में स्थित है",
                    "LIVE_IN": f"{subject} {obj} में रहते हैं",
                    "SPEAK_LANGUAGE": f"{subject} {obj} बोलते हैं",
                    "BELONG_TO": f"{subject} {obj} से संबंधित हैं",
                    "HAS_LANGUAGE": f"{subject} {obj} भाषा का उपयोग करते हैं",
                    "HAS_A_POPULATION": f"{subject} की अनुमानित जनसंख्या {obj} है",
                },
                "zh": {
                    "IS_A": f"{subject}是{obj}",
                    "TYPE": f"{subject}是{obj}",
                    "LOCATED_IN": f"{subject}位于{obj}",
                    "LIVE_IN": f"{subject}居住在{obj}",
                    "SPEAK_LANGUAGE": f"{subject}使用{obj}",
                    "BELONG_TO": f"{subject}属于{obj}",
                    "HAS_LANGUAGE": f"{subject}使用{obj}语言",
                    "HAS_A_POPULATION": f"{subject}的估计人口为{obj}",
                },
            }
            sentence = translated_templates.get(language, {}).get(predicate_key)
            if sentence:
                return sentence + ("。" if language == "zh" else ".")
            localized_relation = {
                "es": f"relación «{raw_predicate}» con",
                "fr": f"relation « {raw_predicate} » avec",
                "hi": f"का संबंध «{raw_predicate}»",
                "zh": f"通过“{raw_predicate}”关系关联到",
            }[language]
            return f"{subject} {localized_relation} {obj}{'。' if language == 'zh' else '.'}"

        is_plural = self._is_plural_subject(subject)
        sentence_builder = self._PREDICATE_TEMPLATES.get(predicate_key)
        if sentence_builder:
            return f"{sentence_builder(self, subject, obj, is_plural)}."
        # Pass the ORIGINAL predicate text (not the upper-cased key) so any
        # camelCase word boundaries it still has are available to humanize.
        readable_predicate = self._humanize_predicate(raw_predicate, is_plural)
        return f"{subject} {readable_predicate} {obj}."

    # Entities that read as a group rather than one named thing -- "the Garo
    # people", "Informants", "Traditional Garo Houses" -- need a plural verb
    # ("face", not "faces"). Curated from the real production graph rather
    # than a general "ends in s" rule: that rule looks appealing (every
    # plural subject here happens to end in "s" or is "people"/"children"),
    # but a blanket version would misfire on this SAME graph -- "Garo
    # Community Health Status" ends in "s" too and is singular. Checked
    # deliberately rather than assumed. A known, bounded list, not a claim
    # of covering every future subject -- see _PREDICATE_TEMPLATES'
    # docstring for the same tradeoff.
    _PLURAL_SUBJECT_SUFFIXES = (
        "people", "authorities", "houses", "utensils", "members", "informants",
        "children", "programs", "domains",
    )

    def _is_plural_subject(self, humanized_subject: str) -> bool:
        lowered = humanized_subject.strip().lower()
        return any(lowered.endswith(suffix) for suffix in self._PLURAL_SUBJECT_SUFFIXES)

    # One sentence-building function per predicate in the current production
    # graph (data/production_graph/, 32 distinct predicates), keyed the same
    # way _format_triple already computed a lookup key. WHY THIS EXISTS: a
    # live test 2026-10-07 ("What is the Garo community?") showed the OLD
    # 8-entry dict matched NONE of the real predicates -- including a literal
    # typo, "LIVE_IN" against the real "LIVING_IN" -- so every answer fell
    # through to naive concatenation: "The Garo people faces Unemployment"
    # (wrong verb number) and "Garo People bilingual Bengali" (missing verb
    # entirely). Each function takes (self, subject, object, is_plural) and
    # returns a sentence with no trailing period. A predicate from a FUTURE
    # paper that isn't one of these 32 falls through to _humanize_predicate's
    # generic word-segmentation path, now at least plural-aware for the
    # common single-word-verb case -- but closing this for good needs a
    # controlled predicate vocabulary at extraction time (KNOWN_LIMITATIONS.md
    # #5), not an ever-growing dict here.
    _PREDICATE_TEMPLATES: Dict[str, Any] = {
        "POPULATION": lambda self, s, o, p: f"{s} recorded a population of {o}",
        "BILINGUAL": lambda self, s, o, p: f"{s} {'are' if p else 'is'} bilingual in {o}",
        "HAD_INTEREST_IN": lambda self, s, o, p: f"{s} had an interest in {o}",
        "HAVE_PROPERTY": lambda self, s, o, p: f"{s} {'have' if p else 'has'} {self._article(o)} as a feature",
        "EVOLVE": lambda self, s, o, p: f"{s} evolved to use {o}",
        "NAMED": lambda self, s, o, p: f"{s} {'are' if p else 'is'} named {o}",
        "HAS_TRADITIONAL_RELIGION": lambda self, s, o, p: f"{s} {'have' if p else 'has'} a traditional religious practice of {o}",
        "HAS_HEALTH_STATUS": lambda self, s, o, p: f"{s} {'have' if p else 'has'} a health status of {o}",
        "HAS_PERCENTAGE": lambda self, s, o, p: f"{s} {'stand' if p else 'stands'} at {o}",
        "FACES": lambda self, s, o, p: f"{s} {'face' if p else 'faces'} {o}",
        "HAS_CONCERN": lambda self, s, o, p: f"{s} {'have' if p else 'has'} a concern about {o}",
        "HAS_ORIGIN": lambda self, s, o, p: f"{s} {'originate' if p else 'originates'} from {o}",
        "LIVING_IN": lambda self, s, o, p: f"{s} {'live' if p else 'lives'} in {o}",
        "LANGUAGE_USED": lambda self, s, o, p: f"{s} {'speak' if p else 'speaks'} {o}",
        "HAS_LANGUAGE_MAINTENANCE": lambda self, s, o, p: f"{s} {'maintain' if p else 'maintains'} {o}",
        "DEFINED_BY": lambda self, s, o, p: f"{s} {'are' if p else 'is'} defined by {o}",
        "IDENTIFIED_DOMAINS": lambda self, s, o, p: f"{s} identified {o} as a domain of language use",
        "USES": lambda self, s, o, p: f"{s} {'use' if p else 'uses'} {o}",
        "HAS_USES_IN": lambda self, s, o, p: f"{s} {'have' if p else 'has'} uses in {o}",
        "ARE_MORE_INVOLVED_THAN": lambda self, s, o, p: f"{s} are more involved than {o}",
        "EXTENT_OF_USE": lambda self, s, o, p: f"{s} {'have' if p else 'has'} an extent of use in {o}",
        "RELIGIOUS_DOMAIN": lambda self, s, o, p: f"{s} {'are' if p else 'is'} characterized by the religious domain of {o}",
        "ISCHRISTIAN": lambda self, s, o, p: f"{s} {'are' if p else 'is'} Christian and attend {o}",
        "HAS_RELIGIOUS_SCRIPT": lambda self, s, o, p: f"{s} {'have' if p else 'has'} a religious script in {o}",
        "IS_MAINTAINED_LESS": lambda self, s, o, p: f"{s} {'are' if p else 'is'} maintained less in {o}",
        "MEDIA_BROADCAST": lambda self, s, o, p: f"{s} {'are' if p else 'is'} broadcast through {o}",
        "IS_USED_IN": lambda self, s, o, p: f"{s} {'are' if p else 'is'} used in {o}",
        "HASPOSITIVEATTITUDES": lambda self, s, o, p: f"{s} {'have' if p else 'has'} positive attitudes toward {o}",
        "EMPHASIZES_LANGUAGES": lambda self, s, o, p: f"{s} {'emphasize' if p else 'emphasizes'} {o}",
        "RESIDENTS": lambda self, s, o, p: f"{s} {'are residents' if p else 'is a resident'} of {o}",
        "ABANDONED": lambda self, s, o, p: f"{s} {'have' if p else 'has'} abandoned {o}",
        "INCLUDES": lambda self, s, o, p: f"{s} {'include' if p else 'includes'} {o}",
    }

    # Makes CamelCase graph identifiers readable in a response, and refers
    # to the Garo people by their full, respectful name rather than just
    # the bare entity label -- but only when used AS a subject. A bare
    # "Garo" as an OBJECT usually names the language, not the people (e.g.
    # LANGUAGE_USED's "GaroCommunity -> Garo"); collapsing it the same way
    # produced a real, confirmed bug: "The Garo people language used The
    # Garo people" (self-referential, from the object also collapsing).
    def _humanize_entity(
        self,
        entity: Any,
        language: str = DEFAULT_LANGUAGE,
        as_subject: bool = True,
    ) -> str:
        raw_text = str(entity or "").strip()
        text = raw_text.replace("_", " ")
        text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
        text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
        if re.fullmatch(r"[A-Za-z0-9_]+", raw_text):
            text = re.sub(r"\s+Community$", "", text, flags=re.IGNORECASE)
        if as_subject and text.strip().lower() in {
            "garo",
            "the garo people",
            "garo people",
            "garo community",
        }:
            text = {
                "en": "the Garo people",
                "es": "el pueblo Garo",
                "fr": "le peuple Garo",
                "hi": "गारो लोग",
                "zh": "加罗人",
            }.get(language, "the Garo people")
        return text[:1].upper() + text[1:] if text else "another entity"

    def _article(self, noun: str) -> str:
        readable_noun = noun[:1].lower() + noun[1:]
        return f"an {readable_noun}" if noun[:1].lower() in "aeiou" else f"a {readable_noun}"

    # Turns graph labels such as LIVE_IN into readable sentence fragments.
    # Some relation names were upper-cased before being stored in Neo4j,
    # which destroys any camelCase word boundaries they had (e.g. "relyingOn"
    # became "RELYINGON" with no way to tell where one word ends and the
    # next begins). For those, fall back to dictionary-based word
    # segmentation so the answer still reads as real words instead of one
    # run-together blob.
    def _humanize_predicate(self, predicate: str, is_plural: bool = False) -> str:
        normalized = predicate.lower().replace("_", " ").strip()
        replacements = {
            "live in": "live in" if is_plural else "lives in",
            "located in": "are located in" if is_plural else "is located in",
            "born in": "were born in" if is_plural else "was born in",
            "part of": "are part of" if is_plural else "is part of",
            "related to": "are related to" if is_plural else "is related to",
            "is a": "are" if is_plural else "is a",
            "role": "have the role of" if is_plural else "has the role of",
            "recognize": "recognize",
            "speak language": "speak",
        }
        if normalized in replacements:
            return replacements[normalized]

        segmented = [
            word
            for token in normalized.split(" ")
            if token
            for word in self._split_concatenated_word(token)
        ]
        # A single segmented word ending in "s" reads as a present-tense,
        # third-person-singular verb (e.g. "faces", "includes") -- the exact
        # shape behind a real, confirmed bug: "The Garo people faces
        # Unemployment". For a plural subject, strip the trailing "s" to the
        # bare/plural verb form. Scoped to a single segment only: a
        # multi-word phrase's trailing "s" is usually a plural NOUN, not a
        # verb (e.g. "identified domains"), where stripping it would be
        # wrong -- "identified domain" is worse, not better.
        if is_plural and len(segmented) == 1 and len(segmented[0]) > 3 and segmented[0].endswith("s"):
            segmented = [segmented[0][:-1]]
        readable = " ".join(segmented)
        return readable or ("are related to" if is_plural else "is related to")

    # Splits a run of letters with no remaining word boundaries (e.g.
    # "relyingon") back into likely English words. Short tokens are left
    # alone since they're either already a real word or too short to
    # segment reliably. Degrades gracefully (returns the token unchanged)
    # if the word-segmentation library isn't installed.
    def _split_concatenated_word(self, token: str) -> List[str]:
        if len(token) <= 7 or not token.isalpha():
            return [token]
        try:
            import wordninja  # type: ignore[import-not-found]
        except ImportError:
            return [token]
        segments = wordninja.split(token)
        return segments if segments else [token]


class RAGQuerySkeleton(Protocol):
    """Shared interface for local and Neo4j-backed retrieval skeletons."""
    def query(self, question: str, top_k: int = 10) -> List[Dict[str, Any]]: ...
    def format_output(self, triples: List[Dict[str, Any]]) -> str: ...
    def close(self) -> None: ...


# Where admin uploads and the decision queue live.
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "uploads"))

# Papers in this corpus run well under 10 MB; the cap stops a single request
# pulling an arbitrary amount into memory.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _confidence_scorer(pdf_path: str):
    """Scores an uploaded paper with the confidence framework.

    Imported lazily so starting the API does not require spaCy, Ollama or the
    framework's own import-time endpoint resolution -- the chatbot must come
    up even when admin ingestion cannot run.
    """
    from confidence_framework import run_confidence_check

    return run_confidence_check(pdf_path)


# Creates an HTTP handler backed by the selected RAG retriever.
def create_query_handler(skeleton: RAGQuerySkeleton, synthesizer: AnswerSynthesizer):
    auth_store: Optional[AuthStore] = None

    def get_auth_store() -> AuthStore:
        nonlocal auth_store
        if auth_store is None:
            auth_store = AuthStore()
        return auth_store

    class QueryHandler(BaseHTTPRequestHandler):
        # Allows Flutter web to preflight cross-origin API requests.
        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        def do_HEAD(self) -> None:
            if self.path.startswith("/tts/audio/"):
                local_tts.handle_audio(self, head=True)
                return
            self._send_json(404, {"error": "Not found"})

        # Handles browser health checks and API requests.
        def do_GET(self) -> None:
            if self.path.startswith("/tts/audio/"):
                local_tts.handle_audio(self)
                return
            if self.path == "/health":
                # Booleans and the process id only, never the secret itself.
                # Lets you confirm which server answered and that it loaded
                # the admin secret.
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "admin_secret_configured": bool(
                            os.getenv("ADMIN_UPLOAD_SECRET")
                        ),
                        "pid": os.getpid(),
                    },
                )
                return
            if self.path == "/feedback":
                user = self._authenticated_user()
                if user is None:
                    return
                try:
                    self._send_json(
                        200,
                        {"feedback": get_auth_store().feedback_for_user(user["email"])},
                    )
                except Exception as error:
                    print(f"Feedback history error: {type(error).__name__}: {error}")
                    self._send_json(
                        503, {"error": "Feedback history is unavailable."}
                    )
                return
            if self.path == "/history":
                user = self._authenticated_user()
                if user is None:
                    return
                try:
                    self._send_json(
                        200,
                        {"conversations": get_auth_store().history_for_user(user["email"])},
                    )
                except Exception as error:
                    print(f"Chat history error: {type(error).__name__}: {error}")
                    self._send_json(503, {"error": "Chat history is unavailable."})
                return
            if self.path == "/admin/users":
                if not self._admin_role_authorised():
                    return
                try:
                    self._send_json(200, {"users": get_auth_store().users()})
                except Exception as error:
                    print(f"Admin user list error: {type(error).__name__}: {error}")
                    self._send_json(503, {"error": "User accounts are unavailable."})
                return
            if urlparse(self.path).path == "/admin/feedback":
                if not self._admin_role_authorised():
                    return
                status = parse_qs(urlparse(self.path).query).get("status", [""])[0].strip()
                if status not in {"", "pending", "reviewed"}:
                    self._send_json(400, {"error": "status must be pending or reviewed."})
                    return
                try:
                    self._send_json(
                        200,
                        {"feedback": get_auth_store().all_feedback(status or None)},
                    )
                except Exception as error:
                    print(f"Admin feedback list error: {type(error).__name__}: {error}")
                    self._send_json(503, {"error": "Feedback is unavailable."})
                return
            if self.path == "/admin/feedback/stats":
                if not self._admin_role_authorised():
                    return
                try:
                    self._send_json(200, get_auth_store().feedback_stats())
                except Exception as error:
                    print(f"Admin feedback stats error: {type(error).__name__}: {error}")
                    self._send_json(503, {"error": "Feedback statistics are unavailable."})
                return
            if self.path == "/admin/queue":
                if not self._admin_authorised():
                    return
                self._send_json(200, {"queue": current_queue(UPLOADS_DIR)})
                return
            if self.path.startswith("/admin/paper"):
                self._handle_paper_download()
                return
            self._send_json(404, {"error": "Not found"})

        def do_PATCH(self) -> None:
            prefix = "/admin/users/"
            if not self.path.startswith(prefix):
                self._send_json(404, {"error": "Not found"})
                return
            if not self._admin_role_authorised():
                return
            current_email = unquote(self.path[len(prefix):]).strip()
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("Request body must be a JSON object.")
                get_auth_store().update_user(
                    current_email=current_email,
                    new_email=str(payload.get("email", "")).strip(),
                    role=str(payload.get("role", "")).strip(),
                    password=str(payload.get("password", "")),
                )
                self._send_json(200, {"status": "updated"})
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                self._send_json(400, {"error": str(error)})
            except Exception as error:
                print(f"Admin user update error: {type(error).__name__}: {error}")
                self._send_json(503, {"error": "User account could not be updated."})

        # Handles questions sent by the Flutter client.
        def do_POST(self) -> None:
            if self.path == "/auth/register":
                self._handle_auth(register=True)
                return
            if self.path == "/auth/login":
                self._handle_auth(register=False)
                return
            if self.path == "/feedback":
                self._handle_feedback()
                return
            if self.path == "/history":
                self._handle_history_save()
                return
            if self.path == "/tts":
                local_tts.handle_post(self)
                return
            if self.path == "/admin/upload":
                self._handle_admin_upload()
                return
            if self.path == "/admin/review":
                self._handle_manual_review()
                return
            if self.path.startswith("/admin/feedback/") and self.path.endswith("/review"):
                self._handle_feedback_review()
                return
            if self.path != "/query":
                self._send_json(404, {"error": "Not found"})
                return
            if self._authenticated_user() is None:
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    self._send_json(400, {"error": "Request body must be a JSON object"})
                    return
                question = str(payload.get("query", "")).strip()
                if not question:
                    self._send_json(400, {"error": "query is required"})
                    return

                language = normalize_language(payload.get("language"))
                english_question = (
                    synthesizer.english_question(question, language) or question
                )
                retrieval_question = synthesizer.question_for_retrieval(
                    question, language, translated=english_question
                )
                # Capped to what synthesizer.answer() actually sends the model
                # (SYNTHESIS_EVIDENCE_LIMIT), not the full DEFAULT_TOP_K=25
                # retrieval. WHY: live-tested 2026-10-07 -- a one-fact answer
                # like "The population... is not explicitly stated..." was
                # showing "View verified sources (25)", because the Flutter
                # client's source count comes straight from this list
                # (chat_service.dart's _readSources(payload['triples'])), and
                # it was never trimmed to match what the model actually saw.
                # A real per-question relevance threshold would be more
                # honest still, but was tested against all of today's example
                # questions and found unsafe to ship: for the religion
                # question fixed earlier today, a threshold would have cut
                # the two genuinely relevant triples (Judgment, Informants)
                # while keeping an irrelevant one that outscores them on a
                # keyword-overlap artifact ("traditional" in both the
                # question and an unrelated subject name). That needs the
                # retrieval scorer's stemming gaps (e.g. "live" vs "living")
                # closed first -- a bigger, separate piece of work.
                triples = skeleton.query(retrieval_question, top_k=SYNTHESIS_EVIDENCE_LIMIT)
                sources = sorted({
                    t.get("source_section", "Unknown")
                    for t in triples
                    if t.get("source_section")
                })
                translate_all = getattr(synthesizer, "answer_translations", None)
                if callable(translate_all):
                    raw_translations = translate_all(
                        question,
                        triples,
                        english_question=english_question,
                        selected_language=language,
                    )
                    if not isinstance(raw_translations, dict):
                        raise TranslationUnavailableError(language)
                    translations = {
                        key: value
                        for key, value in raw_translations.items()
                        if isinstance(key, str) and isinstance(value, str)
                    }
                    answer = translations.get(language)
                    if not answer:
                        raise TranslationUnavailableError(language)
                else:
                    answer = synthesizer.answer(
                        question,
                        triples,
                        language,
                        english_question=english_question,
                    )
                    translations = {language: answer}
                self._send_json(200, {
                    "answer": answer,
                    "language": language,
                    "translations": translations,
                    "evidence": skeleton.format_output(triples),
                    "sources": sources,
                    "triples": triples,
                })
            except TranslationUnavailableError as error:
                self._send_json(
                    503,
                    {
                        "error": (
                            f"Could not translate the answer into "
                            f"{AnswerSynthesizer.SUPPORTED_LANGUAGES[error.language]}. "
                            "Please try again later or select English."
                        ),
                        "language": error.language,
                    },
                )
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                self._send_json(400, {"error": f"Invalid request: {error}"})
            except Exception as error:  # e.g. Neo4j connection or Cypher errors
                # Report the real problem instead of dropping the connection,
                # which the app would otherwise show as "Cannot reach RAG.py".
                print(f"Query backend error: {type(error).__name__}: {error}")
                self._send_json(
                    502,
                    {"error": f"Knowledge graph query failed ({type(error).__name__}: {error}). Check Neo4j URI and network/DNS."},
                )

        def do_DELETE(self) -> None:
            if self.path.startswith("/admin/users/"):
                if not self._admin_role_authorised():
                    return
                email = unquote(self.path[len("/admin/users/"):]).strip()
                try:
                    get_auth_store().delete_user(email)
                    self._send_json(200, {"status": "deleted"})
                except (TypeError, ValueError) as error:
                    self._send_json(400, {"error": str(error)})
                except Exception as error:
                    print(f"Admin user delete error: {type(error).__name__}: {error}")
                    self._send_json(503, {"error": "User account could not be deleted."})
                return
            user = self._authenticated_user()
            if user is None:
                return
            if self.path == "/feedback":
                get_auth_store().delete_feedback(user["email"])
                self._send_json(200, {"status": "deleted"})
                return
            if self.path.startswith("/feedback/"):
                feedback_id = unquote(self.path[len("/feedback/"):]).strip()
                try:
                    get_auth_store().delete_feedback_item(user["email"], feedback_id)
                    self._send_json(200, {"status": "deleted"})
                except ValueError as error:
                    self._send_json(404, {"error": str(error)})
                except Exception as error:
                    print(f"Feedback delete error: {type(error).__name__}: {error}")
                    self._send_json(503, {"error": "Feedback could not be deleted."})
                return
            if self.path.startswith("/history/"):
                conversation_id = self.path.removeprefix("/history/").strip()
                if not conversation_id:
                    self._send_json(400, {"error": "Conversation id is required."})
                    return
                get_auth_store().delete_history(user["email"], conversation_id)
                self._send_json(200, {"status": "deleted"})
                return
            self._send_json(404, {"error": "Not found"})

        def _handle_history_save(self) -> None:
            user = self._authenticated_user()
            if user is None:
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                conversations = payload.get("conversations")
                if not isinstance(conversations, list):
                    raise ValueError("conversations must be a list.")
                get_auth_store().save_history(user["email"], conversations)
                self._send_json(200, {"status": "saved"})
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                self._send_json(400, {"error": f"Invalid history: {error}"})
            except Exception as error:
                print(f"Chat history storage error: {type(error).__name__}: {error}")
                self._send_json(503, {"error": "Chat history storage is unavailable."})

        def _authenticated_user(self) -> Optional[Dict[str, str]]:
            header = self.headers.get("Authorization", "")
            token = header.removeprefix("Bearer ").strip()
            user = get_auth_store().session(token) if token else None
            if user is None:
                self._send_json(401, {"error": "Sign in is required."})
            return user

        def _handle_auth(self, register: bool) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                email = str(payload.get("email", ""))
                username = str(payload.get("username", ""))
                password = str(payload.get("password", ""))
                account = (
                    get_auth_store().register(email, password, username)
                    if register
                    else get_auth_store().login(
                        str(
                            payload.get(
                                "identifier",
                                payload.get("username", email),
                            )
                        ),
                        password,
                    )
                )
                if account is None:
                    self._send_json(401, {"error": "Invalid credentials."})
                    return
                self._send_json(201 if register else 200, account)
            except ValueError as error:
                self._send_json(400, {"error": str(error)})
            except Exception as error:
                if register and "already exists" in str(error).lower():
                    self._send_json(409, {"error": "An account already exists."})
                    return
                print(f"Authentication backend error: {type(error).__name__}: {error}")
                self._send_json(503, {"error": "Authentication service unavailable."})

        def _handle_feedback(self) -> None:
            user = self._authenticated_user()
            if user is None:
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("Request body must be a JSON object.")
                get_auth_store().save_feedback(
                    user_email=user["email"],
                    conversation_id=str(payload.get("conversation_id", "")).strip(),
                    response_text=str(payload.get("response_text", "")).strip(),
                    rating=str(payload.get("rating", "")).strip(),
                    comment=str(payload.get("comment", "")).strip(),
                    triple_ids=payload.get("triple_ids")
                    if isinstance(payload.get("triple_ids"), list)
                    else [],
                )
                self._send_json(201, {"status": "saved"})
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                self._send_json(400, {"error": f"Invalid feedback: {error}"})
            except Exception as error:
                print(f"Feedback storage error: {type(error).__name__}: {error}")
                self._send_json(503, {"error": "Feedback storage is unavailable."})

        # An admin's verdict on one piece of user feedback. Uses the stricter
        # admin-role check, enforced here from the session token. The app
        # hiding the button from non-admins is only cosmetic; this is what
        # actually refuses everyone else (403). Unlike paper upload/review it
        # does not also need the shared ADMIN_UPLOAD_SECRET.
        def _handle_feedback_review(self) -> None:
            if not self._admin_role_authorised():
                return
            admin = self._authenticated_user()
            if admin is None:
                return
            feedback_id = unquote(
                self.path[len("/admin/feedback/"):-len("/review")]
            ).strip()
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("Request body must be a JSON object.")
                archive_ids = payload.get("archive_triple_ids")
                if archive_ids is not None and not (
                    isinstance(archive_ids, list)
                    and all(isinstance(item, str) for item in archive_ids)
                ):
                    raise ValueError("archive_triple_ids must be a list of strings.")
                get_auth_store().review_feedback(
                    feedback_id,
                    admin_email=admin["email"],
                    action=str(payload.get("action", "")).strip(),
                    note=str(payload.get("note", "")).strip(),
                    archive_triples=payload.get("archive_triples") is True,
                    archive_triple_ids=archive_ids,
                    correction=(
                        payload["correction"]
                        if isinstance(payload.get("correction"), dict)
                        else None
                    ),
                )
                self._send_json(200, {"status": "reviewed"})
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                self._send_json(400, {"error": str(error)})
            except Exception as error:
                print(f"Feedback review error: {type(error).__name__}: {error}")
                self._send_json(503, {"error": "The review could not be saved."})

        # Refuses unless the request carries the shared admin secret. The
        # Flutter admin role only decides which buttons render -- a role held
        # in the browser is not access control -- so this is what actually
        # protects an endpoint that spends inference time and writes files.
        def _admin_authorised(self) -> bool:
            user = self._authenticated_user()
            if user is None:
                return False
            if user.get("role") != "admin":
                self._send_json(403, {"error": "Administrator access is required."})
                return False
            expected = os.getenv("ADMIN_UPLOAD_SECRET")
            if check_admin_secret(self.headers.get("X-Admin-Secret"), expected=expected):
                return True
            if not expected:
                self._send_json(503, {"error":
                    "ADMIN_UPLOAD_SECRET is not set on the server, so admin "
                    "endpoints are disabled. Set it in .env."})
            else:
                self._send_json(401, {"error": "Admin secret missing or incorrect."})
            return False

        def _admin_role_authorised(self) -> bool:
            user = self._authenticated_user()
            if user is None:
                return False
            if user.get("role") != "admin":
                self._send_json(403, {"error": "Administrator access is required."})
                return False
            return True

        # Accepts a PDF as the raw request body, with its filename in a header.
        # Raw bytes rather than multipart/form-data on purpose: the stdlib cgi
        # module that parsed multipart was removed in Python 3.13, and a Flutter
        # client posts bodyBytes just as easily.
        def _handle_admin_upload(self) -> None:
            if not self._admin_authorised():
                return

            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                self._send_json(400, {"error": "No file was uploaded."})
                return
            if length > MAX_UPLOAD_BYTES:
                self._send_json(413, {"error":
                    f"That file is {length} bytes; the limit is "
                    f"{MAX_UPLOAD_BYTES}."})
                return

            data = self.rfile.read(length)
            filename = self.headers.get("X-Filename", "")

            # Validated synchronously so a bad upload gets an immediate 400
            # rather than a 202 and silence.
            try:
                name = validate_upload(data, filename)
            except ValueError as error:
                self._send_json(400, {"error": str(error)})
                return

            # Scoring is an LLM job -- minutes per paper on local Ollama, with
            # a 300s timeout per call -- so it cannot run inside the request.
            # The admin polls /admin/queue for the verdict.
            def score_in_background():
                try:
                    ingest_pdf(data, name, scorer=_confidence_scorer,
                               uploads_dir=UPLOADS_DIR)
                except Exception as error:
                    print(f"Admin upload scoring failed for {name}: {error}")

            threading.Thread(target=score_in_background, daemon=True).start()

            self._send_json(202, {
                "status": "scoring",
                "paper": name,
                "message": "Upload accepted and being scored. Poll /admin/queue "
                           "for the verdict; this takes minutes per paper.",
            })

        # Serves a stored PDF so a reviewer can read what they are judging.
        # The paper name travels in the query string, which is fine -- it is
        # not sensitive. The SECRET stays in a header, where it belongs.
        def _handle_paper_download(self) -> None:
            if not self._admin_authorised():
                return

            name = parse_qs(urlparse(self.path).query).get("name", [""])[0]
            try:
                data = read_paper_bytes(name, uploads_dir=UPLOADS_DIR)
            except FileNotFoundError as error:
                self._send_json(404, {"error": str(error)})
                return
            except ValueError as error:
                self._send_json(400, {"error": str(error)})
                return

            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        # Records a person's approve/reject on a paper held for review.
        def _handle_manual_review(self) -> None:
            if not self._admin_authorised():
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                paper = str(payload.get("paper", "")).strip()
                if not paper or "approve" not in payload:
                    raise ValueError("paper and approve are both required")
                approve = bool(payload["approve"])
                note = payload.get("note")
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                self._send_json(400, {"error": f"Invalid request: {error}"})
                return

            try:
                outcome = record_manual_decision(
                    paper, approve=approve, note=note, uploads_dir=UPLOADS_DIR)
            except FileNotFoundError as error:
                self._send_json(404, {"error": str(error)})
                return
            except ValueError as error:
                self._send_json(400, {"error": str(error)})
                return

            self._send_json(200, outcome.to_json())

        # Writes a JSON response with CORS enabled for local Flutter clients.
        def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # Adds the headers required by Flutter web and browser clients.
        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, POST, PATCH, DELETE, OPTIONS",
            )
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization, X-Admin-Secret, X-Filename")

        # Keeps routine request logs concise during local development.
        def log_message(self, format: str, *args: Any) -> None:
            print(f"RAG API: {format % args}")

    return QueryHandler


# Starts the local HTTP bridge used by the Flutter frontend.
def serve_api(kg_path: str, host: str, port: int, approach: str, use_neo4j: bool) -> None:
    skeleton: RAGQuerySkeleton = Neo4jRAGSkeleton() if use_neo4j else RAGSkeleton(kg_path, approach=approach)
    server = ThreadingHTTPServer(
        (host, port),
        create_query_handler(skeleton, AnswerSynthesizer()),
    )
    print(f"RAG API listening on http://{host}:{port}")
    if os.getenv("ADMIN_UPLOAD_SECRET"):
        print("Admin secret: loaded (admin review and upload endpoints enabled)")
    else:
        print(
            "WARNING: ADMIN_UPLOAD_SECRET is not set. Admin review and upload "
            f"will be refused. Add it to {Path(__file__).resolve().parent / '.env'} "
            "and restart."
        )
    print("POST /query with {\"query\": \"your question\"}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\\nStopping RAG API")
    finally:
        server.server_close()
        if use_neo4j:
            skeleton.close()


# ============================================================================
# 6. Command‑Line Interface
# ============================================================================

def main() -> None:
    """
    Parse command‑line arguments and run the appropriate mode:
        - --test-questions : run comparison and print rationale.
        - --query          : answer a single question.
        - (no flags)       : start an interactive session.
    """
    parser = argparse.ArgumentParser(description="RAG Retrieval Comparison")
    parser.add_argument("--kg", action="append", help="Path to KG CSV; repeat to load multiple files")
    parser.add_argument("--test-questions", action="store_true",
                        help="Run comparison with built-in test questions")
    parser.add_argument("--query", help="Single question to test")
    parser.add_argument("--serve", action="store_true",
                        help="Start the HTTP API used by the Flutter frontend")
    parser.add_argument("--neo4j", action="store_true",
                        help="Read Entity relationships directly from Neo4j")
    parser.add_argument("--host", default="127.0.0.1",
                        help="API host (default: 127.0.0.1)")
    # default=None, not 8000: lets a hosting platform's injected $PORT win
    # when --port is not given explicitly, while an explicit --port (local
    # development) still wins over $PORT.
    parser.add_argument("--port", type=int, default=None,
                        help="API port (default: $PORT, or 8000 if that is also unset)")
    parser.add_argument("--approach", choices=["concept", "cypher"], default="concept",
                        help="Retrieval approach (default: concept)")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                        help=f"Number of triples to return (default: {DEFAULT_TOP_K})")
    args = parser.parse_args()
    args.port = resolve_port(args.port)

    # Verify that the KG file exists.
    if args.neo4j and not args.serve:
        parser.error("--neo4j can only be used with --serve")

    if not args.kg and not args.neo4j:
        parser.error("--kg is required unless --neo4j --serve is used")

    for path in args.kg or []:
        if not Path(path).expanduser().is_file():
            parser.error(f"CSV file not found: {path}")

    if args.serve:
        serve_api(args.kg, args.host, args.port, args.approach, args.neo4j)
        return

    # Load the knowledge graph once.
    kg = KnowledgeGraph(args.kg)

    # A comprehensive, respectful list of test questions about the Garo people.
    # The questions are phrased in community‑first language and cover a wide range of topics.
    test_questions = [
        # Identity
        "Who are the Garo people?",
        "What do the Garo people call themselves?",
        "What does the term 'Mande' mean?",
        "How do the Garo people identify themselves?",
        # Language
        "What language do the Garo people speak?",
        "What is the standard dialect of the Garo language?",
        "How many dialects does the Garo language have?",
        "What is the A'we dialect?",
        "Is the Garo language related to other languages?",
        # Demographics and location
        "Where do the Garo people live?",
        "In which Indian states do the Garo people reside?",
        "Do Garo people live in Bangladesh?",
        "What is the population of Garo people in Meghalaya?",
        "Where are the Garo Hills located?",
        "What is the capital of Meghalaya?",
        # Religion and spirituality
        "What is the traditional religion of the Garo people?",
        "What do Songsareks believe in?",
        "What are mitdes according to the Garo people?",
        "What is the role of a shaman in the Garo community?",
        "What happens to the dead in the Garo tradition?",
        "What is a kima?",
        "What is the Wangala festival?",
        "How do the Garo people practice their community religion?",
        "What role do deities play in Garo beliefs?",
        # Christianity
        "What is the current religion of most Garo people?",
        "How did Christianity spread among the Garo people?",
        "Who were the first missionaries to the Garo people?",
        "How have the Garo people responded to Christian missionization?",
        "What is the relationship between traditional Garo beliefs and Christianity?",
        # Agriculture
        "What type of farming do the Garo people practice?",
        "What is shifting cultivation and how do the Garo people practice it?",
        "What crops do the Garo people grow?",
        "What cash crops do the Garo people produce?",
        "What is the main crop of the Garo people?",
        "Do the Garo people grow rice?",
        "What is the importance of rice beer in Garo culture?",
        # Social structure
        "How do the Garo people trace descent?",
        "What is the inheritance system of the Garo people?",
        "Who inherits property among the Garo people?",
        "What is the role of women in Garo society?",
        "What is matrilineal inheritance?",
        "Who is the head of a Garo village?",
        "How is social hierarchy structured among the Garo people?",
        "What is the role of kinship in Garo society?",
        # Festivals and culture
        "What is the Wangala festival and why is it important?",
        "What do the Garo people do during Wangala?",
        "What is the significance of rice beer among the Garo people?",
        "What is a kima and what does it represent?",
        "What is the traditional clothing of the Garo people?",
        "What do the Garo people eat?",
        "What is the role of feasting in Garo culture?",
        # Health
        "How do the Garo people diagnose illness traditionally?",
        "What is the role of deities in illness according to the Garo people?",
        "What is a skal?",
        "What is witchcraft among the Garo people?",
        "How do the Garo people treat illnesses?",
        "How do the Garo people combine traditional and biomedical medicine?",
        # History
        "When did the Garo people first come into contact with the British?",
        "What is the history of the Garo people?",
        "Who wrote about the Garo people in the colonial period?",
        "What is the political structure of the Garo people?",
        # Contemporary
        "What is the current status of Garo culture?",
        "What challenges do the Garo people face today?",
        "What is the relationship between the Garo people and the environment?",
        "What is the role of education among the Garo people?",
        "What is the significance of rice beer among the Garo people?",
        "What is the role of the village headman in Garo society?",
        # General
        "What is the culture of the Garo people?",
        "What are the traditions of the Garo people?",
        "How do the Garo people live?",
        "What is the history of the Garo people?",
        "What is the significance of rice beer among the Garo people?",
        "What is the role of the village headman?",
        "What is the relationship between the Garo people and the environment?"
    ]

    if args.test_questions:
        # Mode 1: Run comparison on a subset of test questions.
        print("=" * 70)
        print("RAG RETRIEVAL COMPARISON")
        print(f"KG: {args.kg} ({len(kg.triples)} triples)")
        print("=" * 70)

        comparator = RetrieverComparator(kg)
        # We test the first 10 questions to keep the output manageable.
        # Remove the slice to test all questions.
        results = comparator.compare(test_questions[:10])
        comparator.print_summary(results)
        comparator.print_rationale(results)   # Data‑driven decision rationale

    elif args.query:
        # Mode 2: Single query.
        skeleton = RAGSkeleton(args.kg, approach=args.approach)
        triples = skeleton.query(args.query, top_k=args.top_k)
        print(f"\nQuestion: {args.query}")
        print(f"Approach: {args.approach}")
        print(f"Triples retrieved: {len(triples)}")
        print("\n" + "-" * 40)
        print(skeleton.format_output(triples))

    else:
        # Mode 3: Interactive session.
        print("=" * 70)
        print("RAG Skeleton – Question → Retrieval → Triples")
        print(f"KG: {args.kg} ({len(kg.triples)} triples)")
        print(f"Approach: {args.approach}")
        print("Type your question (or 'exit' to quit)")
        print("=" * 70)

        skeleton = RAGSkeleton(args.kg, approach=args.approach)
        while True:
            q = input("\n> ")
            if q.lower() in ['exit', 'quit']:
                break
            if not q.strip():
                continue
            triples = skeleton.query(q, top_k=args.top_k)
            print(f"\nTriples retrieved: {len(triples)}")
            print("-" * 40)
            print(skeleton.format_output(triples))


if __name__ == "__main__":
    main()
