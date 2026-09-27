#!/usr/bin/env python3
"""CLI: score an extraction CSV against the manual ground truth.

    python -m eval.run_eval output/garo_1_page3_variantA.csv --pages 3 --label "Variant A"

Never touches Neo4j. Appends one row to eval/results.csv (creating the header
if it doesn't exist yet). See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §7.3.

Note: load_extracted() reads every row in the input CSV -- it does NOT filter
by page. The input CSV must already be scoped to the pages you pass via
--pages (e.g. score a single page's output like garo_1_page3_variantA.csv,
not a whole-paper CSV, when using --pages 3), or off-page rows will be
counted as false positives against the page-filtered ground truth."""

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from eval.ground_truth import DEFAULT_GT_PATH, load_final_triples, triples_for_pages
from eval.hallucination import compute_hallucination_rate, load_page_texts, load_rows
from eval.scorer import ScoreReport, Triple, score

DEFAULT_RESULTS_PATH = str(Path(__file__).resolve().parent / "results.csv")

RESULTS_FIELDS = [
    "timestamp", "label", "csv_path", "pages",
    "tp_strict", "fp_strict", "fn_strict",
    "tp_lenient", "fp_lenient", "fn_lenient",
    "precision_strict", "recall_strict", "f1_strict",
    "precision_lenient", "recall_lenient", "f1_lenient",
    "gt_miss_rate", "triples_per_page",
    # Real, grounding-based hallucination rate (eval/hallucination.py) --
    # only populated when --pdf is given; blank otherwise. Not the same
    # thing as gt_miss_rate above -- see that field's docstring in scorer.py.
    # citation_coverage is the fraction of rows that had a sentence_ref to
    # check at all -- a low value means hallucination_rate rests on thin
    # evidence (an extraction path that doesn't populate citations), not a
    # confident measurement, and must be read alongside it, never alone.
    "hallucination_rate", "citation_coverage",
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
                   results_path: str = DEFAULT_RESULTS_PATH,
                   hallucination_rate: float | None = None,
                   citation_coverage: float | None = None) -> None:
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
            report.gt_miss_rate, report.triples_per_page,
            "" if hallucination_rate is None else hallucination_rate,
            "" if citation_coverage is None else citation_coverage,
        ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Score an extraction CSV against the manual ground truth.")
    parser.add_argument("csv_path")
    parser.add_argument(
        "--pages", required=True,
        help="Comma-separated page numbers, e.g. '3' or '1,4,5'. Only filters the "
        "ground truth -- load_extracted() does NOT filter the input CSV by page, "
        "so the CSV itself must already be scoped to these pages.",
    )
    parser.add_argument("--label", required=True, help="Name for this run, e.g. 'Variant A (broad-v2)'")
    parser.add_argument("--gt-path", default=DEFAULT_GT_PATH)
    parser.add_argument("--results-path", default=DEFAULT_RESULTS_PATH)
    parser.add_argument(
        "--pdf",
        help="Path to the source PDF. When given, also computes the real, "
        "grounding-based hallucination_rate (eval/hallucination.py) by checking "
        "each row's own citation against its page of this PDF -- independent of "
        "gt_miss_rate, which only compares against --gt-path's ground truth.",
    )
    args = parser.parse_args()

    pages = [p.strip() for p in args.pages.split(",") if p.strip()]
    extracted = load_extracted(args.csv_path)
    ground_truth = triples_for_pages(load_final_triples(args.gt_path), pages)
    gt_triples: list[Triple] = [(t.subject, t.predicate, t.object) for t in ground_truth]

    report = score(extracted, gt_triples, num_pages=len(pages))

    hallucination_rate = None
    citation_coverage = None
    if args.pdf:
        page_texts = load_page_texts(args.pdf)
        rows = load_rows(args.csv_path)
        hreport = compute_hallucination_rate(rows, page_texts)
        hallucination_rate = hreport.hallucination_rate
        citation_coverage = hreport.citation_coverage

    append_result(report, args.label, args.csv_path, args.pages, args.results_path,
                  hallucination_rate=hallucination_rate, citation_coverage=citation_coverage)

    if hallucination_rate is None:
        hallucination_str = "n/a (pass --pdf)"
    else:
        hallucination_str = f"{hallucination_rate:.2f} (citation_coverage={citation_coverage:.2f})"
    print(
        f"{args.label}: TP-strict={report.tp_strict} TP-lenient={report.tp_lenient} "
        f"P/R/F1(strict)={report.precision_strict:.2f}/{report.recall_strict:.2f}/{report.f1_strict:.2f} "
        f"gt_miss_rate={report.gt_miss_rate:.2f} hallucination_rate={hallucination_str} "
        f"triples_per_page={report.triples_per_page:.1f}"
    )
    print(f"Appended to {args.results_path}")


if __name__ == "__main__":
    main()
