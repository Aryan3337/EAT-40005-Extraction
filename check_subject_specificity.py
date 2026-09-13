#!/usr/bin/env python3
"""
check_subject_specificity.py -- REPORT-ONLY CLI over subject_specificity.py.

Prints what apply_subject_corrections() would do against a saved CSV,
without changing anything, using the exact same classification logic the
pipeline itself now uses automatically (main.py / run_page_pipeline.py both
call apply_subject_corrections() directly -- this script is for inspecting
past runs or auditing a CSV by hand, not part of the pipeline itself).

USAGE:
    python check_subject_specificity.py output/garo_1_page4_kg.csv
    python check_subject_specificity.py output/garo_1_kg.csv --community-subjects GaroCommunity,GaroPeople
"""

import argparse
import csv
from collections import Counter

from subject_specificity import classify_subject, normalize_to_entity_name


def audit(rows, community_subjects):
    community_subjects_lower = {s.strip().lower() for s in community_subjects}
    results = []
    for row in rows:
        subj = (row.get("subject") or "").strip()
        if subj.lower() not in community_subjects_lower:
            continue
        result = classify_subject(row)
        result["extraction_number"] = row.get("extraction_number")
        result["subject"] = subj
        result["predicate"] = row.get("predicate")
        result["object"] = row.get("object")
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_file", help="Path to a triples CSV (e.g. output/garo_1_page4_kg.csv)")
    parser.add_argument("--community-subjects", default="GaroCommunity,GaroPeople",
                        help="Comma-separated subject names to audit (default: GaroCommunity,GaroPeople)")
    args = parser.parse_args()

    with open(args.csv_file, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    community_subjects = args.community_subjects.split(",")
    results = audit(rows, community_subjects)

    counts = Counter(r["status"] for r in results)
    print(f"Audited {len(results)} triples with subject in {community_subjects}")
    for status, count in counts.most_common():
        print(f"  {status}: {count}")
    print()

    for r in results:
        if r["status"] == "flag":
            new_name = normalize_to_entity_name(r["candidate_subject"])
            print(f"[flag -> WOULD AUTO-CORRECT] #{r['extraction_number']} ({r['subject']})-[{r['predicate']}]->({r['object']})")
            print(f"    {r['subject']} --> {new_name}  (from candidate phrase '{r['candidate_subject']}')")
            print(f"    sentence: {r['sentence'][:120]}")
            print()
        elif r["status"].startswith("flag"):
            print(f"[{r['status']} -- not auto-corrected] #{r['extraction_number']} ({r['subject']})-[{r['predicate']}]->({r['object']})")
            print(f"    candidate subject: '{r['candidate_subject']}'  |  sentence: {r['sentence'][:100]}")
            print()


if __name__ == "__main__":
    main()
