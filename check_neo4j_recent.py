#!/usr/bin/env python3
"""
check_neo4j_recent.py -- inspect what's actually in Neo4j for a paper, and
tell you which of it came from the most recent pipeline run.

WHY THIS EXISTS RATHER THAN A PLAIN CYPHER QUERY:
insert_triple() (neo4j_loader/insert.py) never sets a created_at/updated_at
property on the relationships it MERGEs -- only source_file, source_section,
confidence, passage, sentence_ref. So a query filtered on
r.source_file = 'garo_1.pdf' returns EVERY triple ever uploaded for this
paper across every run (the full-paper run, plus the earlier page 3/4/5
test runs from this session) with no way to tell which run produced which
relationship from inside Neo4j alone.

The one place that DOES unambiguously reflect exactly what the most recent
run uploaded is the local backup CSV main.py/run_page_pipeline.py writes
right before calling add_triples() -- same (subject, predicate, object)
triples, same order, written every run. So this script cross-references
Neo4j's current state against that CSV: anything in Neo4j that matches a
row in the CSV is "from this run"; anything in Neo4j that doesn't is
"stale" -- left over from an earlier run that this run didn't reproduce
(MERGE never deletes, so old data like this just accumulates until
cleaned up separately).

USAGE:
    python check_neo4j_recent.py papers/garo_1.pdf
    python check_neo4j_recent.py papers/garo_1.pdf output/garo_1_kg.csv
"""

import csv
import sys
from pathlib import Path

from neo4j_loader.connection import get_driver
from neo4j_loader.cleaner import clean_relation


def load_recent_run_triples(csv_path: str):
    """Returns a set of (subject, clean_relation(predicate), object) tuples
    exactly as insert_triple() would have written them to Neo4j -- same
    normalization (clean_relation upper-cases and sanitizes the predicate
    into the relationship type), so this matches Neo4j's type(r) directly."""
    triples = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            subj = (row.get("subject") or "").strip()
            pred = clean_relation((row.get("predicate") or "").strip() or "RELATED_TO")
            obj = (row.get("object") or "").strip()
            if subj and obj:
                triples.add((subj, pred, obj))
    return triples


def main():
    if len(sys.argv) < 2:
        print("Usage: python check_neo4j_recent.py <path_to_pdf> [csv_path]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    source_file = Path(pdf_path).name
    paper_name = Path(pdf_path).stem

    csv_path = sys.argv[2] if len(sys.argv) > 2 else f"output/{paper_name}_kg.csv"
    if not Path(csv_path).exists():
        print(f"Backup CSV not found at {csv_path} -- can't tell recent from stale without it.")
        print("Pass the CSV path explicitly if it's somewhere else, e.g.:")
        print(f"  python check_neo4j_recent.py {pdf_path} output/{paper_name}_kg.csv")
        sys.exit(1)

    recent_triples = load_recent_run_triples(csv_path)
    print(f"Loaded {len(recent_triples)} unique triples from this run's backup: {csv_path}")

    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (s)-[r]->(o)
            WHERE r.source_file = $source_file
            RETURN s.name AS subject, type(r) AS predicate, o.name AS object,
                   r.confidence AS confidence, r.source_section AS page
            ORDER BY page, subject
            """,
            source_file=source_file,
        )
        rows = [dict(record) for record in result]

    print(f"\n{len(rows)} relationships currently in Neo4j tagged source_file = '{source_file}'")

    recent, stale = [], []
    for row in rows:
        key = (row["subject"], row["predicate"], row["object"])
        (recent if key in recent_triples else stale).append(row)

    print(f"  {len(recent)} match this run's backup CSV (from this run)")
    print(f"  {len(stale)} do NOT match (left over from an earlier run)")

    # Per-page breakdown, using source_section ("Page N") -- useful for
    # spotting whether every expected page actually landed.
    pages = {}
    for row in rows:
        pages.setdefault(row["page"] or "Unknown", []).append(row)
    print("\nBy page:")
    for page in sorted(pages, key=lambda p: (len(p), p)):
        page_rows = pages[page]
        page_recent = sum(1 for r in page_rows if (r["subject"], r["predicate"], r["object"]) in recent_triples)
        print(f"  {page}: {len(page_rows)} relationships ({page_recent} from this run)")

    if stale:
        print(f"\nStale relationships (source_file matches but not in {csv_path} -- from an earlier run):")
        for row in stale:
            print(f"  ({row['subject']})-[{row['predicate']}]->({row['object']})  [{row['page']}, conf={row['confidence']}]")
        print("\nThese aren't deleted automatically (MERGE only creates/updates). Say the word if you want a cleanup script.")
    else:
        print("\nNo stale relationships -- everything currently in Neo4j for this paper matches the most recent run.")


if __name__ == "__main__":
    main()
