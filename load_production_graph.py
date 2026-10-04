#!/usr/bin/env python3
"""Load the gated triples into the production Neo4j graph.

Loads output/<paper>_kg_refined.csv for each paper named, which is the
post-gate output of main.py -- well-formedness, grounding and
quote-genuineness already applied. It never extracts and never calls an LLM,
so it runs in seconds.

    python load_production_graph.py --dry-run              # default papers
    python load_production_graph.py garo_1 garo_2 garo_3
    python load_production_graph.py --dry-run garo_2

Every relationship is stamped with one run_id for the whole load, so what
this wrote can be found, audited or rolled back afterwards -- see
neo4j_loader/insert.py. The run id is printed and written to
output/load_runs.log; record it next to whatever you were loading, because a
run id nobody wrote down is no better than not having one.

WHY A SEPARATE SCRIPT: main.py extracts and then loads, which is ~1.2 hours
per paper. The production graph is built from corpora that were already
extracted, so re-running main.py to reach its upload step would waste hours
of LLM time reproducing CSVs that are already on disk.
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PAPERS = ["garo_1", "garo_2", "garo_3"]
LOAD_LOG = Path("output") / "load_runs.log"

# output/ is gitignored, so it holds the freshest files but only on the
# machine that produced them. data/production_graph/ is the tracked copy, so
# a clean clone and a hosted container can still load the graph.
CORPUS_DIRS = (Path("output"), Path("data") / "production_graph")


def refined_path(paper: str) -> Path:
    name = f"{paper}_kg_refined.csv"
    for directory in CORPUS_DIRS:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return CORPUS_DIRS[0] / name


def load_rows(paper: str) -> list[dict]:
    path = refined_path(paper)
    if not path.exists():
        raise SystemExit(
            f"Missing {path}.\n\n"
            f"Gate the extraction CSV first:\n"
            f"    python run_verification_pipeline.py output/{paper}_kg.csv \\\n"
            f"        --wellformedness-check --grounding-check --quote-check \\\n"
            f"        --pdf papers/{paper}.pdf"
        )
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check_rows_are_loadable(paper: str, rows: list[dict]) -> list[str]:
    """Problems that would silently produce a worse graph if ignored."""
    problems = []
    if not rows:
        problems.append(f"{paper}: refined CSV has no rows")
        return problems

    missing_source = sum(1 for r in rows if not (r.get("source_file") or "").strip())
    if missing_source:
        problems.append(
            f"{paper}: {missing_source} of {len(rows)} rows have no source_file, "
            f"so their provenance would be unattributable in the graph. The "
            f"CSV was probably produced by run_verification_pipeline.py, which "
            f"preserves only the input's own columns; re-run through main.py "
            f"to get source_file and page_number."
        )

    missing_citation = sum(1 for r in rows if not (r.get("sentence_ref") or "").strip())
    if missing_citation:
        problems.append(
            f"{paper}: {missing_citation} rows have no sentence_ref -- the "
            f"chatbot shows that as the source for every fact, so it would "
            f"display an unsupported claim"
        )
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("papers", nargs="*", default=DEFAULT_PAPERS,
                        help=f"Paper stems to load (default: {' '.join(DEFAULT_PAPERS)})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report exactly what would be loaded and send nothing.")
    parser.add_argument("--run-id",
                        help="Override the generated run id with a meaningful one.")
    args = parser.parse_args()

    papers = args.papers or DEFAULT_PAPERS

    triples = []
    per_paper = {}
    problems = []
    for paper in papers:
        rows = load_rows(paper)
        problems += check_rows_are_loadable(paper, rows)
        per_paper[paper] = len(rows)
        triples += rows

    print("Gated triples ready to load:")
    for paper, count in per_paper.items():
        print(f"  {paper:12s} {count:4d}")
    print(f"  {'TOTAL':12s} {len(triples):4d}")

    if problems:
        print("\nProblems:")
        for problem in problems:
            print(f"  - {problem}")
        if not args.dry_run:
            raise SystemExit("\nRefusing to load. Fix the above, or re-run with --dry-run to inspect.")

    if not triples:
        raise SystemExit("\nNothing to load.")

    if args.dry_run:
        print(f"\n[DRY RUN] Would load {len(triples)} triples. Nothing was sent.")
        print("Re-run without --dry-run once NEO4J_* is configured in .env.")
        return

    # Imported here, not at module level, so --dry-run works with no
    # database configured at all.
    try:
        import config
    except Exception as error:
        raise SystemExit(f"Could not read Neo4j configuration: {error}")

    if not (config.URI and config.USERNAME and config.PASSWORD):
        raise SystemExit(
            "NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD must all be set in "
            ".env before loading. See .env.example.\n\n"
            "If the AuraDB instance does not exist yet, use --dry-run."
        )

    from neo4j_loader.insert import add_triples

    print(f"\nLoading into {config.URI} ...")
    inserted, skipped, run_id = add_triples(triples, run_id=args.run_id)

    LOAD_LOG.parent.mkdir(exist_ok=True)
    entry = (f"{datetime.now(timezone.utc).isoformat()}\t{run_id}\t"
             f"papers={','.join(papers)}\tinserted={inserted}\tskipped={skipped}\n")
    with open(LOAD_LOG, "a", encoding="utf-8") as f:
        f.write(entry)

    print(f"\nRecorded in {LOAD_LOG}")
    print(f"\nTo see only what this load wrote:")
    print(f"    MATCH ()-[r]->() WHERE r.run_id = '{run_id}' RETURN r")
    print(f"To find triples an earlier load left behind:")
    print(f"    MATCH ()-[r]->() WHERE r.run_id <> '{run_id}' RETURN r")


if __name__ == "__main__":
    sys.exit(main())
