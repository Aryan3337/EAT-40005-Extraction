#!/usr/bin/env python3
"""
dry_run_check.py -- test the validation gate and subject-correction step
against an already-saved CSV, with NO Ollama call and NO Neo4j write. Use
this to sanity-check a code change before spending time on a real
extraction run, or to see what a past run's output would look like under
the current code.

USAGE:
    python dry_run_check.py output/garo_1_page3_kg.csv

This mirrors main.py / run_page_pipeline.py's own order of operations
(validate -> subject-correct) but only prints what would happen -- it
never calls add_triples() and never overwrites the CSV.
"""

import argparse
import csv
import sys

from Extraction_Check import validate_triple_format
from subject_specificity import apply_subject_corrections


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_file", help="Path to a triples CSV (e.g. output/garo_1_page3_kg.csv)")
    args = parser.parse_args()

    with open(args.csv_file, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} triples from {args.csv_file}\n")

    # Stage 1: validation gate (structural + placeholder-evidence check)
    print("=" * 60)
    print("STAGE 1: Validation gate")
    print("=" * 60)
    valid_rows = []
    for r in rows:
        try:
            validate_triple_format(r)
            valid_rows.append(r)
        except AssertionError as e:
            print(f"  [REJECTED] #{r.get('extraction_number','?')} ({r.get('subject','?')})-[{r.get('predicate','?')}]->({r.get('object','?')})")
            print(f"             reason: {e}")
    print(f"\n{len(valid_rows)}/{len(rows)} would pass validation.\n")

    if not valid_rows:
        print("Nothing left to check for subject correction.")
        sys.exit(0)

    # Stage 2: subject-specificity auto-correction (preview only -- this
    # mutates the in-memory copy, not the CSV on disk)
    print("=" * 60)
    print("STAGE 2: Subject-specificity correction")
    print("=" * 60)
    _, corrections = apply_subject_corrections(valid_rows)
    if corrections:
        print(f"{len(corrections)} triples would be auto-corrected:\n")
        for c in corrections:
            print(f"  #{c['extraction_number']}: {c['old_subject']} -> {c['new_subject']}   [{c['predicate']}]->({c['object']})")
    else:
        print("No subject corrections would be applied.")

    print(f"\nFinal count if this were a real run: {len(valid_rows)} triples uploaded, {len(corrections)} of them subject-corrected.")


if __name__ == "__main__":
    main()
