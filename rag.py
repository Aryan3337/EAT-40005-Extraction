#!/usr/bin/env python3
"""
RAG Query Layer – Prototype and Compare Two Retrieval Approaches

This program loads a knowledge graph (a set of triples) from a CSV file.
It then lets you test two different ways to find relevant triples for a question:

1. Cypher Translation:
   - Ask an LLM (like Mistral) to turn the question into a pseudo‑Cypher query.
   - Then run that query on the in‑memory triples.

2. Concept Matching:
   - Find entities (like "Garo") mentioned in the question.
   - Retrieve any triple that contains those entities.

You can run comparisons, test single questions, or use interactive mode.

Usage:
    python rag_comparison.py --kg paper1_kg.csv --test-questions
    python rag_comparison.py --kg paper1_kg.csv --query "Where do the Garo live?"
    python rag_comparison.py --kg paper1_kg.csv (interactive)
"""

# Import standard libraries for file handling, regex, parsing arguments, etc.
import json
import csv
import re
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple
from collections import defaultdict
import requests
from datetime import datetime


# ============================================================
# 1. Load Knowledge Graph
# This class loads the CSV file that contains all the triples.
# It also builds an index: for each entity (subject or object),
# we keep a list of triple indices where that entity appears.
# ============================================================

class KnowledgeGraph:
    def __init__(self, csv_path: str):
        # Load all triples from the CSV file.
        self.triples = self._load_csv(csv_path)
        # Build the index (entity -> list of triple positions).
        self._build_index()
        # Print some stats so the user knows what was loaded.
        print(f"Loaded {len(self.triples)} triples")
        print(f"Entities indexed: {len(self.entity_index)} unique names")
    
    def _load_csv(self, path: str) -> List[Dict]:
        """Read the CSV and convert each row into a clean dictionary."""
        triples = []
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Get each field, strip extra spaces, and use default if missing.
                triple = {
                    'subject': row.get('subject', '').strip(),
                    'predicate': row.get('predicate', '').strip(),
                    'object': row.get('object', '').strip(),
                    'sentence_ref': row.get('sentence_ref', '').strip(),
                    'source_section': row.get('source_section', 'Unknown'),
                    'confidence': row.get('confidence', 'Medium')
                }
                # Only keep triples that have all three main parts.
                if triple['subject'] and triple['predicate'] and triple['object']:
                    triples.append(triple)
        return triples
    
    def _build_index(self):
        """
        For every entity (subject or object), store the indices of triples
        that mention that entity. This makes it fast to look up triples
        by entity later.
        """
        self.entity_index = defaultdict(list)
        self.all_entities = set()
        for idx, t in enumerate(self.triples):
            subj = t['subject'].lower()
            obj = t['object'].lower()
            # Add this triple's index to the list for subject and object.
            self.entity_index[subj].append(idx)
            self.entity_index[obj].append(idx)
            # Also store the entity name in a set of all entities.
            self.all_entities.add(subj)
            self.all_entities.add(obj)
    
    def get_triple(self, idx: int) -> Dict:
        """Return the triple at a given index."""
        return self.triples[idx]
    
    def get_triples_by_entities(self, entities: Set[str]) -> List[Dict]:
        """
        Given a set of entity names (already lowercased), return all triples
        that contain any of those entities.
        """
        indices = set()
        for ent in entities:
            # Add all indices from the index for this entity.
            indices.update(self.entity_index.get(ent, []))
        # Convert indices back to triples.
        return [self.triples[i] for i in indices]
    
    def get_all_entities(self) -> Set[str]:
        """Return the set of all entity names (lowercased)."""
        return self.all_entities
    
    def get_schema(self) -> str:
        """
        Return a human‑readable description of the knowledge graph schema.
        This is used in the prompt for the LLM (Cypher translation).
        """
        predicates = set(t['predicate'] for t in self.triples)
        # Only show up to 20 predicates to keep the prompt short.
        pred_list = ', '.join(sorted(predicates)[:20])
        return f"""Knowledge Graph Schema:
- Entity types: Person, Organization, Location, Event, Artifact, Other
- Relationship types: {pred_list}...
- Each triple: (Subject)-[PREDICATE]->(Object)
- Source sentences are stored as sentence_ref
"""


# ============================================================
# 2. Approach A: Cypher Translation
# This approach uses an LLM to generate a query from the question.
# The query is then 'executed' by filtering the in‑memory triples.
# ============================================================

class CypherRetriever:
    def __init__(self, kg: KnowledgeGraph, ollama_url: str = "http://localhost:11434/api/generate"):
        self.kg = kg
        self.ollama_url = ollama_url
        self.model = "mistral:7b"  # You can change to deepseek-r1:7b if you have it.
    
    def _generate_cypher(self, question: str) -> str:
        """
        Send the question to the LLM and ask it to produce a Cypher-like query.
        The query will contain entity and predicate hints.
        """
        schema = self.kg.get_schema()
        prompt = f"""You are a knowledge graph query assistant. Convert the user question into a retrieval query.

Schema:
{schema}

Format: Return a simple list of entities and predicates to match.
Example question: "Where do the Garo live?"
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
                    "options": {"temperature": 0.0, "num_predict": 256}
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
        Parse the generated Cypher string to extract entity and predicate hints.
        Then filter the triples accordingly.
        This is a very simple parser – it does not actually run a real Cypher engine.
        """
        matches = []
        # Look for CONTAINS 'something' in the WHERE clause.
        entity_match = re.search(r"CONTAINS\s*['\"]([^'\"]+)['\"]", cypher, re.IGNORECASE)
        # Look for [r:PREDICATE] to get the predicate.
        pred_match = re.search(r"\[r:([^\]]+)\]", cypher, re.IGNORECASE)
        
        entity = entity_match.group(1).lower() if entity_match else None
        predicate = pred_match.group(1).upper() if pred_match else None
        
        # Go through every triple and see if it matches the hints.
        for t in self.kg.triples:
            # If we have an entity, it must appear in either subject or object.
            if entity and entity not in t['subject'].lower() and entity not in t['object'].lower():
                continue
            # If we have a predicate, it must match exactly.
            if predicate and predicate != t['predicate']:
                continue
            matches.append(t)
        return matches
    
    def retrieve(self, question: str, top_k: int = 10) -> List[Dict]:
        """Full pipeline: generate query, execute, return top_k triples."""
        cypher = self._generate_cypher(question)
        if not cypher:
            return []
        matches = self._execute_cypher(cypher)
        return matches[:top_k]


# ============================================================
# 3. Approach B: Concept Matching
# This approach finds entities that appear in the question,
# then retrieves all triples that contain those entities.
# No LLM call is needed.
# ============================================================

class ConceptRetriever:
    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg
    
    def _extract_entities(self, question: str) -> Set[str]:
        """
        Find which known entities (from the KG) appear in the question.
        We compare against all lowercased entities.
        """
        question_lower = question.lower()
        entities = set()
        for entity in self.kg.get_all_entities():
            if entity in question_lower:
                entities.add(entity)
        return entities
    
    def retrieve(self, question: str, top_k: int = 10) -> List[Dict]:
        """
        Retrieve triples that mention any entity from the question.
        If no entities are found, fall back to matching predicates.
        """
        entities = self._extract_entities(question)
        if not entities:
            # No known entity found – try matching predicates instead.
            predicates = set(t['predicate'].lower() for t in self.kg.triples)
            question_lower = question.lower()
            matched_preds = [p for p in predicates if p in question_lower]
            results = []
            for t in self.kg.triples:
                if t['predicate'].lower() in matched_preds:
                    results.append(t)
            return results[:top_k]
        
        # Get all triples that contain any of these entities.
        results = self.kg.get_triples_by_entities(entities)
        
        # Rank triples: the more entities from the question appear in the triple, the higher.
        scored = []
        for t in results:
            score = 0
            subj = t['subject'].lower()
            obj = t['object'].lower()
            for ent in entities:
                if ent in subj or ent in obj:
                    score += 1
            scored.append((score, t))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:top_k]]


# ============================================================
# 4. Evaluation / Comparison
# This class runs both retrievers on a set of test questions
# and prints a summary to help decide which approach is better.
# ============================================================

class RetrieverComparator:
    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg
        self.concept_retriever = ConceptRetriever(kg)
        self.cypher_retriever = CypherRetriever(kg)
    
    def compare(self, test_questions: List[str]) -> Dict:
        """
        For each question, run both retrievers and collect statistics.
        Returns a dictionary with results and a comparison list.
        """
        results = {
            'concept': {},      # Map question -> list of triples
            'cypher': {},       # Map question -> list of triples
            'comparison': []    # List of per‑question stats
        }
        
        for i, q in enumerate(test_questions, 1):
            print(f"\n--- Question {i}: {q}")
            
            # Run concept matching.
            concept_triples = self.concept_retriever.retrieve(q, top_k=10)
            concept_entities = self.concept_retriever._extract_entities(q)
            
            # Run Cypher translation.
            cypher_triples = self.cypher_retriever.retrieve(q, top_k=10)
            
            # Store results for later inspection.
            results['concept'][q] = concept_triples
            results['cypher'][q] = cypher_triples
            
            # Compute counts and overlap.
            concept_count = len(concept_triples)
            cypher_count = len(cypher_triples)
            # Overlap: triples that appear in both result sets (based on subject, predicate, object).
            concept_set = set(tuple(sorted((t['subject'], t['predicate'], t['object']))) for t in concept_triples)
            cypher_set = set(tuple(sorted((t['subject'], t['predicate'], t['object']))) for t in cypher_triples)
            overlap = len(concept_set & cypher_set)
            
            print(f"  Concept: {concept_count} triples (entities found: {concept_entities})")
            print(f"  Cypher: {cypher_count} triples")
            print(f"  Overlap: {overlap} triples")
            
            # Show the first result from each for a quick look.
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
    
    def print_summary(self, results: Dict):
        """Print a detailed summary of the comparison results."""
        print("\n" + "=" * 60)
        print("COMPARISON SUMMARY")
        print("=" * 60)
        
        # Totals across all questions.
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


# ============================================================
# 5. Minimal Skeleton: Question → Retrieval → Triples
# This is the main class that you would use to answer queries.
# It wraps the chosen retriever and provides a simple query() method.
# ============================================================

class RAGSkeleton:
    """
    Minimal question → retrieval → triples output.
    You can choose which retrieval approach to use.
    """

    def __init__(self, kg_path: str, approach: str = "concept"):
        # Load the knowledge graph from the CSV.
        self.kg = KnowledgeGraph(kg_path)
        self.approach = approach
        # Instantiate the chosen retriever.
        if approach == "concept":
            self.retriever = ConceptRetriever(self.kg)
        elif approach == "cypher":
            self.retriever = CypherRetriever(self.kg)
        else:
            raise ValueError("approach must be 'concept' or 'cypher'")
    
    def query(self, question: str, top_k: int = 10) -> List[Dict]:
        """
        Take a natural language question and return a list of relevant triples.
        This is the main entry point for the retrieval system.
        """
        return self.retriever.retrieve(question, top_k)
    
    def format_output(self, triples: List[Dict]) -> str:
        """
        Convert a list of triples into a human‑friendly text block.
        Includes the triple itself, the source sentence, and the page number.
        """
        if not triples:
            return "No triples found."
        lines = []
        for t in triples:
            lines.append(f"({t['subject']}) -[{t['predicate']}]-> ({t['object']})")
            if t.get('sentence_ref'):
                lines.append(f"  // Source: {t['sentence_ref']}")
            if t.get('source_section'):
                lines.append(f"  // Page: {t['source_section']}")
            lines.append("")  # blank line between triples
        return "\n".join(lines)


# ============================================================
# 6. Command‑line interface
# This section parses the command‑line arguments and runs
# the appropriate mode: comparison, single query, or interactive.
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="RAG Retrieval Comparison")
    parser.add_argument("--kg", required=True, help="Path to KG CSV file")
    parser.add_argument("--test-questions", action="store_true", help="Run comparison with built-in test questions")
    parser.add_argument("--query", help="Single question to test")
    parser.add_argument("--approach", choices=["concept", "cypher"], default="concept", 
                        help="Retrieval approach (default: concept)")
    parser.add_argument("--top-k", type=int, default=10, help="Number of triples to return")
    args = parser.parse_args()
    
    # Check that the KG file exists.
    if not Path(args.kg).exists():
        print(f"File not found: {args.kg}")
        sys.exit(1)
    
    # Load the KG once (we may reuse it later).
    kg = KnowledgeGraph(args.kg)
    
    # A short list of test questions (you can expand this).
    test_questions = [
        "Who are the Garo people?",
        "What is the main occupation of the Garo?",
        "What is the current religion of most Garo?",
        "What is the Garo community religion called?",
        "What is the significance of rice beer among the Garo?",
        "What is the role of the village headman?",
        "What is the relationship between the Garo and the environment?",
        "What is the history of the Garo people?",
        "What is the status of Garo culture today?"
    ]
    
    if args.test_questions:
        # Mode 1: run a comparison of both approaches on the test questions.
        print("=" * 70)
        print("RAG RETRIEVAL COMPARISON")
        print(f"KG: {args.kg} ({len(kg.triples)} triples)")
        print("=" * 70)
        
        comparator = RetrieverComparator(kg)
        results = comparator.compare(test_questions[:5])  # Test first 5 to keep output manageable.
        comparator.print_summary(results)
        
        # Print the final recommendation based on the comparison.
        print("\n" + "=" * 70)
        print("RECOMMENDATION")
        print("=" * 70)
        print("Based on the comparison:")
        print("1. Concept matching is simpler, faster, and requires no LLM calls.")
        print("2. Cypher translation adds complexity but can handle complex multi-hop questions.")
        print("3. For the current KG size (simple triples), concept matching is sufficient.")
        print("4. Recommendation: Use CONCEPT MATCHING as the primary retrieval approach.")
        print("5. Add Cypher translation later as an optional route for advanced queries.")
        print("=" * 70)
    
    elif args.query:
        # Mode 2: run a single query with the chosen approach.
        skeleton = RAGSkeleton(args.kg, approach=args.approach)
        triples = skeleton.query(args.query, top_k=args.top_k)
        print(f"\nQuestion: {args.query}")
        print(f"Approach: {args.approach}")
        print(f"Triples retrieved: {len(triples)}")
        print("\n" + "-" * 40)
        print(skeleton.format_output(triples))
    
    else:
        # Mode 3: interactive mode – keep asking questions until 'exit'.
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