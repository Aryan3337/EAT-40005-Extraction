#!/usr/bin/env python3
"""CLI: score an extraction CSV against the manual ground truth.

    python -m eval.run_eval output/garo_1_page3_variantA.csv --pages 3 --label "Variant A"

Never touches Neo4j. Appends one row to eval/results.csv (creating the header
if it doesn't exist yet). See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §7.3."""

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from eval.ground_truth import DEFAULT_GT_PATH, load_final_triples, triples_for_pages
from eval.scorer import ScoreReport, Triple, score

DEFAULT_RESULTS_PATH = str(Path(__file__).resolve().parent / "results.csv")

RESULTS_FIELDS = [
    "timestamp", "label", "csv_path", "pages",
    "tp_strict", "fp_strict", "fn_strict",
    "tp_lenient", "fp_lenient", "fn_lenient",
    "precision_strict", "recall_strict", "f1_strict",
    "precision_lenient", "recall_lenient", "f1_lenient",
    "hallucination_rate", "triples_per_page",
]


def load_extracted(csv_path: str) -> list[Triple]:
    """Reads subject/predicate/object columns from an extraction CSV. Works
    with either output shape the pipeline produces (test_extraction.py's
    page_number/subject/predicate/object/confidence_score, or main.py's
    extraction_number/paper/subject/predicate/object/source_section/...)
    since only the three shared column names are read."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [(row["subject"], row["predicate"], row["object"]) for row in reader]


def append_result(report: ScoreReport, label: str, csv_path: str, pages: str,
                   results_path: str = DEFAULT_RESULTS_PATH) -> None:
    results_file = Path(results_path)
    write_header = not results_file.exists()
    with open(results_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(RESULTS_FIELDS)
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            label, csv_path, pages,
            report.tp_strict, report.fp_strict, report.fn_strict,
            report.tp_lenient, report.fp_lenient, report.fn_lenient,
            report.precision_strict, report.recall_strict, report.f1_strict,
            report.precision_lenient, report.recall_lenient, report.f1_lenient,
            report.hallucination_rate, report.triples_per_page,
        ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Score an extraction CSV against the manual ground truth.")
    parser.add_argument("csv_path")
    parser.add_argument("--pages", required=True, help="Comma-separated page numbers, e.g. '3' or '1,4,5'")
    parser.add_argument("--label", required=True, help="Name for this run, e.g. 'Variant A (broad-v2)'")
    parser.add_argument("--gt-path", default=DEFAULT_GT_PATH)
    parser.add_argument("--results-path", default=DEFAULT_RESULTS_PATH)
    args = parser.parse_args()

    pages = [p.strip() for p in args.pages.split(",") if p.strip()]
    extracted = load_extracted(args.csv_path)
    ground_truth = triples_for_pages(load_final_triples(args.gt_path), pages)
    gt_triples: list[Triple] = [(t.subject, t.predicate, t.object) for t in ground_truth]

    report = score(extracted, gt_triples, num_pages=len(pages))
    append_result(report, args.label, args.csv_path, args.pages, args.results_path)

    print(
        f"{args.label}: TP-strict={report.tp_strict} TP-lenient={report.tp_lenient} "
        f"P/R/F1(strict)={report.precision_strict:.2f}/{report.recall_strict:.2f}/{report.f1_strict:.2f} "
        f"hallucination_rate={report.hallucination_rate:.2f} triples_per_page={report.triples_per_page:.1f}"
    )
    print(f"Appended to {args.results_path}")


if __name__ == "__main__":
    main()
