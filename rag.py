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
import re
import sys
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple, Optional, Protocol
from collections import defaultdict
from dotenv import load_dotenv
import requests

try:
    from neo4j import GraphDatabase  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency for Neo4j mode
    GraphDatabase = None

load_dotenv()


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
        self.ollama_url = ollama_url or os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
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
    Retrieves triples by extracting known entities from the question using word‑boundary matching.
    If no entities are found, it falls back to matching predicates or searching the sentence_ref fields.

    This approach is fast, deterministic, and does not require an LLM.
    It is the recommended primary retrieval strategy.
    """

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg
        # Common stopwords to ignore when extracting keywords.
        self.stopwords = {'what', 'is', 'are', 'the', 'of', 'in', 'for', 'on', 'at', 'to', 'with',
                          'by', 'from', 'up', 'about', 'do', 'does', 'did', 'have', 'has', 'had',
                          'how', 'why', 'when', 'where', 'which', 'who', 'whom', 'whose'}

    def _extract_entities(self, question: str) -> Set[str]:
        """
        Find known entities from the KG that appear in the question as whole words.
        This avoids partial matches (e.g., 'Garo' should not match 'GaroWomen').
        """
        question_lower = question.lower()
        entities = set()
        for entity in self.kg.get_all_entities():
            if re.search(r'\b' + re.escape(entity) + r'\b', question_lower):
                entities.add(entity)
        return entities

    def _extract_keywords(self, question: str) -> List[str]:
        """
        Extract meaningful keywords (words with at least 3 letters, excluding stopwords).
        These are used for predicate matching and sentence search fallbacks.
        """
        question_lower = question.lower()
        words = re.findall(r'\b[a-z][a-z]{2,}\b', question_lower)
        return [w for w in words if w not in self.stopwords]

    def _match_predicates(self, question: str) -> List[Dict]:
        """
        Find triples whose predicate contains any of the keywords extracted from the question.
        This is useful when the question does not mention a known entity but does describe a relationship.
        """
        keywords = self._extract_keywords(question)
        results = []
        for t in self.kg.triples:
            pred = t['predicate'].lower()
            if any(kw in pred or pred in kw for kw in keywords):
                results.append(t)
        return results

    def _search_sentences(self, question: str) -> List[Dict]:
        """
        Final fallback: search the sentence_ref fields of all triples for keywords.
        This can retrieve triples whose source sentence contains the relevant terms,
        even if the triple itself does not directly match the question.
        """
        keywords = self._extract_keywords(question)
        results = []
        for t in self.kg.triples:
            sent = t.get('sentence_ref', '').lower()
            if sent and any(kw in sent for kw in keywords):
                results.append(t)
        return results

    def retrieve(self, question: str, top_k: int = 10) -> List[Dict]:
        """
        Main retrieval pipeline:
            1. Attempt to extract known entities from the question.
            2. If entities are found, retrieve all triples containing them and rank by relevance.
            3. If no entities, try matching predicates.
            4. If still nothing, search sentence references.

        Ranking is based on:
            - Number of entity matches (weighted 2 points each).
            - Keyword matches in the predicate (1 point each).
            - Length of the sentence_ref (longer = more context).
        """
        entities = self._extract_entities(question)
        if entities:
            results = self.kg.get_triples_by_entities(entities)
            scored = []
            for t in results:
                score = 0
                subj = t['subject'].lower()
                obj = t['object'].lower()
                for ent in entities:
                    if ent in subj or ent in obj:
                        score += 2
                pred_lower = t['predicate'].lower()
                for kw in self._extract_keywords(question):
                    if kw in pred_lower:
                        score += 1
                # Add a small bonus for longer sentence references (more informative).
                score += len(t.get('sentence_ref', '')) / 200
                scored.append((score, t))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [t for _, t in scored[:top_k]]

        # No entities found – try predicate matching.
        pred_results = self._match_predicates(question)
        if pred_results:
            return pred_results[:top_k]

        # Final fallback – search sentence references.
        sent_results = self._search_sentences(question)
        return sent_results[:top_k]


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
            print("  ✅ Select Concept Matching as the primary retrieval approach.")
            print(f"     It retrieved {total_concept - total_cypher} more triples overall and returned something for {concept_nonzero - cypher_nonzero} more questions.")
            print("     For the current KG (simple triples, single‑hop facts), this is the most reliable and efficient choice.")
        else:
            print("  ⚠️ Consider Cypher Translation if complex queries become frequent.")

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

    def query(self, question: str, top_k: int = 10) -> List[Dict]:
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
    def query(self, question: str, top_k: int = 10) -> List[Dict]:
        keywords = [word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", question)]
        if not keywords:
            return []
        
        question_lower = question.lower()
        relationship_terms = []
        if re.search(r"\b(where|live|lives|located|location|reside|resides|home)\b", question_lower):
            relationship_terms.extend(["live", "locat", "resid", "home", "place"])
        if re.search(r"\b(language|speak|speaks|dialect)\b", question_lower):
            relationship_terms.extend(["speak", "language", "dialect"])
        if re.search(r"\b(population|many|number)\b", question_lower):
            relationship_terms.extend(["population", "number", "count"])
        if re.search(r"\b(what is|who is|what are|who are)\b", question_lower):
            relationship_terms.extend(["is_a", "type", "identity", "about"])

        cypher = """
        MATCH (s:Entity)-[r]->(o:Entity)
        WHERE any(keyword IN $keywords WHERE
            toLower(coalesce(s.name, '')) CONTAINS keyword OR
            toLower(coalesce(o.name, '')) CONTAINS keyword OR
            toLower(coalesce(r.passage, '')) CONTAINS keyword OR
            toLower(coalesce(r.sentence_ref, '')) CONTAINS keyword)
        WITH s, r, o, keywords,
             reduce(score = 0, term IN $relationship_terms |
                 score + CASE
                     WHEN toLower(type(r)) CONTAINS term THEN 10
                     WHEN toLower(coalesce(r.passage, '')) CONTAINS term THEN 5
                     ELSE 0
                 END) AS relevance
        RETURN s.name AS subject,
               type(r) AS predicate,
               o.name AS object,
               coalesce(r.sentence_ref, '') AS sentence_ref,
               coalesce(r.source_section, '') AS source_section,
               coalesce(r.passage, '') AS passage,
               coalesce(r.confidence, '') AS confidence
        ORDER BY relevance DESC
        LIMIT $top_k
        """

        with self.driver.session() as session:
            result = session.run(
                cypher,
                keywords=keywords,
                relationship_terms=relationship_terms,
                top_k=top_k,
            )
            return [dict(record) for record in result]

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
class AnswerSynthesizer:
    def __init__(self, ollama_url: Optional[str] = None, model: Optional[str] = None):
        self.ollama_url = ollama_url or os.getenv(
            "OLLAMA_URL", "http://localhost:11434/api/generate"
        )
        self.model = model or os.getenv("OLLAMA_MODEL", "deepseek-r1:7b")

    # Writes a natural-language answer while keeping every claim tied to evidence.
    def answer(self, question: str, triples: List[Dict[str, Any]]) -> str:
        if not triples:
            return "I could not find enough connected evidence to answer that question. Try naming a specific person, place, event, or relationship."

        prompt = self._build_prompt(question, triples)
        try:
            response = requests.post(
                self.ollama_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 400},
                },
                timeout=30,
            )
            if response.status_code == 200:
                text = response.json().get("response", "").strip()
                if text:
                    return self._clean_response(text)
        except (requests.RequestException, ValueError, KeyError) as error:
            print(f"Answer synthesis unavailable: {error}")

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
        predicate = str(triple.get("predicate", "")).upper().replace(" ", "_")
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
        sentence = templates.get(predicate)
        if sentence:
            return f"{sentence}."
        readable_predicate = self._humanize_predicate(predicate)
        return f"{subject} {readable_predicate} {obj}."

    # Makes CamelCase graph identifiers readable in a response.
    def _humanize_entity(self, entity: Any) -> str:
        raw_text = str(entity or "").strip()
        text = raw_text.replace("_", " ")
        text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
        text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
        if re.fullmatch(r"[A-Za-z0-9_]+", raw_text):
            text = re.sub(r"\s+Community$", "", text, flags=re.IGNORECASE)
        return text[:1].upper() + text[1:] if text else "another entity"

    def _article(self, noun: str) -> str:
        readable_noun = noun[:1].lower() + noun[1:]
        return f"an {readable_noun}" if noun[:1].lower() in "aeiou" else f"a {readable_noun}"

    # Turns graph labels such as LIVE_IN into readable sentence fragments.
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
        return replacements.get(normalized, normalized or "is related to")


class RAGQuerySkeleton(Protocol):
    """Shared interface for local and Neo4j-backed retrieval skeletons."""
    def query(self, question: str, top_k: int = 10) -> List[Dict[str, Any]]: ...
    def format_output(self, triples: List[Dict[str, Any]]) -> str: ...
    def close(self) -> None: ...


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
            self._send_json(404, {"error": "Not found"})

        # Handles questions sent by the Flutter client.
        def do_POST(self) -> None:
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
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

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
    parser.add_argument("--port", type=int, default=8000,
                        help="API port (default: 8000)")
    parser.add_argument("--approach", choices=["concept", "cypher"], default="concept",
                        help="Retrieval approach (default: concept)")
    parser.add_argument("--top-k", type=int, default=10,
                        help="Number of triples to return (default: 10)")
    args = parser.parse_args()

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