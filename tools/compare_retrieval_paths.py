#!/usr/bin/env python3
"""Compare the graph retrieval path against the CSV path over the SAME triples.

Verification harness for NECTAR_BACKLOG.md G1 (porting `matches_topic` to
`Neo4jRAGSkeleton.query`). Run it before the change to reproduce the figures
the backlog cites, and after to confirm the gap has closed.

WHY THIS EXISTS: the two paths differ in two ways at once -- the code that
ranks and filters, AND the data they read (AuraDB holds 715 relationships
against the 112-triple CSV export). Comparing the deployed API against the
CSV fallback would conflate the two. This loads the CSV corpus once and runs
BOTH algorithms over it, so the only variable left is the code.

    python tools/compare_retrieval_paths.py
    python tools/compare_retrieval_paths.py --top-k 6
    python tools/compare_retrieval_paths.py --question "Where do the Garo live?"

No Neo4j connection, no LLM, no network. Deterministic.

Reading the output: "off-topic" counts triples the graph path returns that
the CSV path rejects. Those are what reaches answer synthesis as evidence on
the deployed system. After G1, it should be 0.
"""

import argparse
import collections
import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rag  # noqa: E402
from rag import (  # noqa: E402
    SYNTHESIS_EVIDENCE_LIMIT,
    KnowledgeGraph,
    dedupe_triples,
    keyword_weights,
    question_keywords,
    score_triple_weighted,
    topic_focused,
)

# The 8 questions the backlog's figures were measured on. Chosen to span the
# corpus's topics rather than to flatter either path -- four of them show no
# difference at all, which is the point: an unrepresentative set would make
# the gap look either worse or better than it is.
BENCHMARK_QUESTIONS = [
    "What languages do the Garo speak?",
    "What is the traditional religion of the Garo?",
    "Where do the Garo live?",
    "What medicinal plants are used?",
    "How has Garo livelihood changed?",
    "What is the Garo population?",
    "Tell me about matrilineal inheritance",
    "What happens during antepartum care?",
]

# Fields Neo4jRAGSkeleton.query's Cypher WHERE clause matches on. Note
# `passage`, which is NOT in rag._FIELD_WEIGHTS -- so a triple can match the
# Cypher and still score 0, which is what the `score > 0` cut removes.
CYPHER_MATCH_FIELDS = ("subject", "object", "predicate", "sentence_ref", "passage")


def load_corpus():
    paths = sorted(glob.glob("data/production_graph/*_kg_refined.csv"))
    if not paths:
        sys.exit(
            "No CSVs found in data/production_graph/.\n"
            "Run this from the repository root."
        )
    return KnowledgeGraph(paths)


def graph_path(kg, question, top_k):
    """What Neo4jRAGSkeleton.query does, with Cypher's WHERE simulated locally.

    Mirrors rag.py's Neo4jRAGSkeleton.query: candidate set by keyword
    CONTAINS, weighted scoring, stable sort, topic filter, dedupe, truncate.

    It calls rag.topic_focused rather than reimplementing it, so this cannot
    drift from the code it is meant to measure. Before G1 landed (2026-10-28)
    this function deliberately had no topic filter, because that absence was
    what the harness existed to measure; the filter is in the graph path now,
    so the mirror carries it too.

    The `score > 0` cut is in the graph path now as well, but is deliberately
    NOT mirrored here: the "score 0" column exists to report how many triples
    that cut removes, and applying it here would drive the column to 0 by
    construction and measure nothing. It has read 0 on this corpus before and
    after G1, which is the backlog's own finding -- the cut is a guard against
    `passage`- and `question`-only matches, not a measured win.
    """
    keywords = question_keywords(question)
    if not keywords:
        return [], {}
    candidates = [
        triple
        for triple in kg.triples
        if any(
            keyword in str(triple.get(field) or "").lower()
            for keyword in keywords
            for field in CYPHER_MATCH_FIELDS
        )
    ]
    weights = keyword_weights(keywords, candidates)
    candidates = sorted(
        candidates, key=lambda triple: -score_triple_weighted(triple, weights)
    )
    candidates = topic_focused(keywords, candidates)
    return dedupe_triples(candidates)[:top_k], weights


def csv_path(kg, question, top_k):
    return rag.ConceptRetriever(kg).retrieve(question, top_k)


def identity(triple):
    return (triple.get("subject"), triple.get("predicate"), triple.get("object"))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--top-k",
        type=int,
        default=SYNTHESIS_EVIDENCE_LIMIT,
        help="Evidence window. Defaults to rag.SYNTHESIS_EVIDENCE_LIMIT "
        f"({SYNTHESIS_EVIDENCE_LIMIT}), which is what rag.py's /query handler "
        "actually passes to skeleton.query -- so the default reflects "
        "production rather than a round number.",
    )
    parser.add_argument(
        "--question",
        action="append",
        help="Ask one question instead of the benchmark set. Repeatable.",
    )
    args = parser.parse_args()

    kg = load_corpus()
    questions = args.question or BENCHMARK_QUESTIONS
    top_k = args.top_k

    print(f"\n{len(kg.triples)} triples, top_k={top_k}\n")
    header = f"{'question':<46}{'graph':>6}{'csv':>5}{'score 0':>9}{'off-topic':>11}"
    print(header)
    print("-" * len(header))

    total_zero = total_offtopic = 0
    detail = []
    for question in questions:
        found, weights = graph_path(kg, question, top_k)
        kept = csv_path(kg, question, top_k)
        zero_scoring = [
            t for t in found if score_triple_weighted(t, weights) == 0
        ]
        kept_ids = {identity(t) for t in kept}
        off_topic = [t for t in found if identity(t) not in kept_ids]
        total_zero += len(zero_scoring)
        total_offtopic += len(off_topic)
        if off_topic:
            detail.append((question, off_topic, weights))
        print(
            f"{question:<46}{len(found):>6}{len(kept):>5}"
            f"{len(zero_scoring):>9}{len(off_topic):>11}"
        )

    print("-" * len(header))
    print(f"{'TOTAL':<46}{'':>6}{'':>5}{total_zero:>9}{total_offtopic:>11}")

    if detail:
        print("\n\nTriples the graph path returns and the CSV path rejects")
        print("(these are what reaches answer synthesis as evidence):\n")
        for question, off_topic, weights in detail:
            print(f"  {question}")
            for triple in off_topic:
                score = score_triple_weighted(triple, weights)
                print(
                    f"    score {score:6.2f}  ({triple['subject']}) "
                    f"-[{triple['predicate']}]-> ({triple['object']})"
                )
            print()

    print(
        f"\nRESULT: off-topic = {total_offtopic}, zero-scoring = {total_zero}.\n"
        "G1 is done when off-topic reaches 0 without the CSV column dropping."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
