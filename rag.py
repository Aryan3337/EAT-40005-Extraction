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
import threading
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple, Optional, Protocol
from collections import defaultdict
from dotenv import load_dotenv
import requests

from admin_ingest import (check_admin_secret, current_queue, ingest_pdf,
                          read_paper_bytes, record_manual_decision,
                          validate_upload)
from llm_endpoint import ollama_tunnel_headers, resolve_llm_endpoint

try:
    from neo4j import GraphDatabase  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency for Neo4j mode
    GraphDatabase = None

load_dotenv()


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


def _keyword_in_triple(triple: Dict[str, Any], keyword: str) -> bool:
    for field, _ in _FIELD_WEIGHTS:
        if keyword in str(triple.get(field) or "").lower():
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
            if keyword in haystack:
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
        self.triples = self._load_csv(csv_path)
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
                    'subject': row.get('subject', '').strip(),
                    'predicate': row.get('predicate', '').strip(),
                    'object': row.get('object', '').strip(),
                    'sentence_ref': row.get('sentence_ref', '').strip(),
                    'source_section': row.get('source_section', 'Unknown'),
                    'confidence': row.get('confidence', 'Medium')
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
        weights = keyword_weights(keywords, self.kg.triples)
        scored = [(score_triple_weighted(triple, weights), triple) for triple in self.kg.triples]
        # Stable sort on the negated score keeps the CSV's row order as the
        # tie-break, so equal-scoring results do not shuffle between calls.
        scored.sort(key=lambda pair: -pair[0])
        matches = [triple for score, triple in scored if score > 0]
        return dedupe_triples(matches)[:top_k]


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
        WHERE any(keyword IN $keywords WHERE
            toLower(coalesce(s.name, '')) CONTAINS keyword OR
            toLower(coalesce(o.name, '')) CONTAINS keyword OR
            toLower(type(r)) CONTAINS keyword OR
            toLower(coalesce(r.sentence_ref, '')) CONTAINS keyword OR
            toLower(coalesce(r.passage, '')) CONTAINS keyword)
        RETURN s.name AS subject,
               type(r) AS predicate,
               o.name AS object,
               coalesce(r.sentence_ref, '') AS sentence_ref,
               coalesce(r.source_section, '') AS source_section,
               coalesce(r.passage, '') AS passage,
               coalesce(r.confidence, '') AS confidence,
               coalesce(r.run_id, '') AS run_id,
               coalesce(r.ingested_at, '') AS ingested_at
        LIMIT $fetch_limit
        """

        with self.driver.session() as session:
            result = session.run(
                cypher,
                keywords=keywords,
                fetch_limit=self.FETCH_LIMIT,
            )
            candidates = [dict(record) for record in result]

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


class AnswerSynthesizer:
    def __init__(self, ollama_url: Optional[str] = None, model: Optional[str] = None,
                 answer_cache: Optional[Dict[str, str]] = None):
        # Answer synthesis sends sentence_ref -- verbatim paper text -- to
        # the model on every query, so this is the call site that most
        # needs the guard. Checked at construction: the hosted deployment
        # runs with no LLM at all and answers from _fallback_answer.
        self.ollama_url = resolve_llm_endpoint(
            ollama_url or os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
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

    # Writes a natural-language answer while keeping every claim tied to evidence.
    def answer(self, question: str, triples: List[Dict[str, Any]]) -> str:
        if not triples:
            return "I could not find enough connected evidence to answer that question. Try naming a specific person, place, event, or relationship."

        cached = self.answer_cache.get(normalize_cache_key(question))
        if cached:
            return cached

        prompt = self._build_prompt(question, triples[:SYNTHESIS_EVIDENCE_LIMIT])
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 400},
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
                if response.status_code == 200:
                    text = response.json().get("response", "").strip()
                    if text:
                        return self._clean_response(text)
                break

        return self._fallback_answer(triples)

    # Builds a small evidence-only prompt for the local language model.
    def _build_prompt(self, question: str, triples: List[Dict[str, Any]]) -> str:
        evidence = []
        for triple in triples:
            evidence.append({
                "subject": triple.get("subject", ""),
                "relationship": triple.get("predicate", ""),
                "object": triple.get("object", ""),
                "source_context": triple.get("sentence_ref", ""),
                "source_section": triple.get("source_section", ""),
            })

        return f"""You are a careful knowledge-graph research assistant.
Answer the user's question using only the evidence below.
The Mandi people are the same community as the Garo people (they call themselves
A·chik Mande), so treat "Mandi", "Mande", "A·chik" and "Garo" as the same people.
Do not invent facts, names, dates, or explanations that are not supported.
    If the question asks what an entity is, begin with a direct definition and then add
    one or two supported details such as location, language, or community identity.
    Translate graph identifiers such as GaroCommunity into natural language such as
    "the Garo community". Write 1-3 natural paragraphs. Do not mention prompts,
    models, retrieval, graph triples, or JSON.
    Answer the specific question first and omit evidence that does not help answer it.
    If the evidence is incomplete, say what is known and briefly acknowledge the limitation.

User question:
{question}

Evidence:
{json.dumps(evidence, ensure_ascii=False, indent=2)}

Answer:"""

    # Removes model-style prefixes that do not belong in the chat response.
    def _clean_response(self, text: str) -> str:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"^\s*(answer|response)\s*:\s*", "", text, flags=re.IGNORECASE)
        return text.strip()

    # Produces a readable answer when Ollama is offline or unavailable.
    def _fallback_answer(self, triples: List[Dict[str, Any]]) -> str:
        statements = [self._format_triple(triple) for triple in triples[:6]]
        statements = [statement for statement in statements if statement]
        if not statements:
            return "I could not find enough connected evidence to answer that question."
        return "Based on the available knowledge, " + " ".join(statements)

    # Converts one graph triple into a readable, grounded sentence.
    def _format_triple(self, triple: Dict[str, Any]) -> str:
        subject = self._humanize_entity(triple.get("subject", "This entity"))
        raw_predicate = str(triple.get("predicate", ""))
        predicate_key = raw_predicate.upper().replace(" ", "_")
        obj = self._humanize_entity(triple.get("object", "another entity"))
        subject_lower = subject.lower()

        templates = {
            "IS_A": f"{subject} is {self._article(obj)}",
            "TYPE": f"{subject} is {self._article(obj)}",
            "LOCATED_IN": f"{subject} is located in {obj}",
            "LIVE_IN": f"{subject} live in {obj}" if subject_lower.endswith("people") else f"{subject} lives in {obj}",
            "SPEAK_LANGUAGE": f"{subject} speak {obj}" if subject_lower.endswith("people") or subject_lower.endswith("community") else f"{subject} speaks {obj}",
            "BELONG_TO": f"{subject} belong to {obj}" if subject_lower.endswith("people") or subject_lower.endswith("community") else f"{subject} belongs to {obj}",
            "HAS_LANGUAGE": f"{subject} use the {obj} language",
            "HAS_A_POPULATION": f"{subject} have an estimated population of {obj}",
        }
        sentence = templates.get(predicate_key)
        if sentence:
            return f"{sentence}."
        # Pass the ORIGINAL predicate text (not the upper-cased key) so any
        # camelCase word boundaries it still has are available to humanize.
        readable_predicate = self._humanize_predicate(raw_predicate)
        return f"{subject} {readable_predicate} {obj}."

    # Makes CamelCase graph identifiers readable in a response, and refers
    # to the Garo people by their full, respectful name rather than just
    # the bare entity label.
    def _humanize_entity(self, entity: Any) -> str:
        raw_text = str(entity or "").strip()
        text = raw_text.replace("_", " ")
        text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
        text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
        if re.fullmatch(r"[A-Za-z0-9_]+", raw_text):
            text = re.sub(r"\s+Community$", "", text, flags=re.IGNORECASE)
        if text.strip().lower() == "garo":
            text = "the Garo people"
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
    def _humanize_predicate(self, predicate: str) -> str:
        normalized = predicate.lower().replace("_", " ").strip()
        replacements = {
            "live in": "lives in",
            "located in": "is located in",
            "born in": "was born in",
            "part of": "is part of",
            "related to": "is related to",
            "is a": "is a",
            "role": "have the role of",
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
        readable = " ".join(segmented)
        return readable or "is related to"

    # Splits a run of letters with no remaining word boundaries (e.g.
    # "relyingon") back into likely English words. Short tokens are left
    # alone since they're either already a real word or too short to
    # segment reliably. Degrades gracefully (returns the token unchanged)
    # if the word-segmentation library isn't installed.
    def _split_concatenated_word(self, token: str) -> List[str]:
        if len(token) <= 7 or not token.isalpha():
            return [token]
        try:
            import wordninja
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
    class QueryHandler(BaseHTTPRequestHandler):
        # Allows Flutter web to preflight cross-origin API requests.
        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        # Handles browser health checks and API requests.
        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"status": "ok"})
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

        # Handles questions sent by the Flutter client.
        def do_POST(self) -> None:
            if self.path == "/admin/upload":
                self._handle_admin_upload()
                return
            if self.path == "/admin/review":
                self._handle_manual_review()
                return
            if self.path != "/query":
                self._send_json(404, {"error": "Not found"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                question = str(payload.get("query", "")).strip()
                if not question:
                    self._send_json(400, {"error": "query is required"})
                    return

                triples = skeleton.query(question)
                sources = sorted({
                    t.get("source_section", "Unknown")
                    for t in triples
                    if t.get("source_section")
                })
                self._send_json(200, {
                    "answer": synthesizer.answer(question, triples),
                    "evidence": skeleton.format_output(triples),
                    "sources": sources,
                    "triples": triples,
                })
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

        # Refuses unless the request carries the shared admin secret. The
        # Flutter admin role only decides which buttons render -- a role held
        # in the browser is not access control -- so this is what actually
        # protects an endpoint that spends inference time and writes files.
        def _admin_authorised(self) -> bool:
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
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, X-Admin-Secret, X-Filename")

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
    parser.add_argument("--kg", help="Path to KG CSV file")
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

    if args.kg and not Path(args.kg).exists():
        print(f"File not found: {args.kg}")
        sys.exit(1)

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