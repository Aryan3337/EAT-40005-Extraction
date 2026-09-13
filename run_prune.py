#!/usr/bin/env python3
"""
CLI for running the pruner -- either as part of your ingestion pipeline
(call it right after loading a new batch) or manually against the whole
graph.

Usage:
    # Preview what would happen to a specific batch, no writes:
    python run_prune.py --batch-id 2026-09-09-mandi-interview-04 --dry-run

    # Actually prune that batch:
    python run_prune.py --batch-id 2026-09-09-mandi-interview-04

    # Full-graph sweep (e.g. a one-off cleanup of everything already loaded):
    python run_prune.py --full-scan

    # Skip the LLM judge (e.g. no API key configured yet):
    python run_prune.py --batch-id ... --no-llm-judge

Note: the current ingestion pipeline (main.py / neo4j_loader/insert.py)
doesn't tag anything with batch_id yet, so --batch-id will always match
zero rows against real data -- use --full-scan until that's added.
"""

import argparse
import json
import logging

from pruner.core import prune_batch


def main():
    parser = argparse.ArgumentParser(description="Prune noisy triples from the Neo4j knowledge graph.")
    parser.add_argument("--batch-id", default=None, help="Only process nodes/relationships tagged with this batch_id.")
    parser.add_argument("--full-scan", action="store_true", help="Ignore --batch-id and scan the whole graph.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen without changing the graph.")
    parser.add_argument("--no-llm-judge", action="store_true", help="Skip Tier 3 (useful if no LLM backend is configured yet).")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                         format="%(asctime)s %(levelname)s %(message)s")

    batch_id = None if args.full_scan else args.batch_id
    if not args.full_scan and not args.batch_id:
        parser.error("Pass --batch-id <id>, or --full-scan to sweep the whole graph.")

    summary = prune_batch(batch_id=batch_id, dry_run=args.dry_run, run_llm_judge=not args.no_llm_judge)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
