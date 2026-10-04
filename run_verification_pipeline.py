#!/usr/bin/env python3
"""Takes an already-produced extraction CSV and runs the deterministic
well-formedness, grounding and/or quote checks on it. Never imports
neo4j_loader, never calls add_triples(). See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §7.5.

    python run_verification_pipeline.py output/garo_1_page3_variantA.csv \\
        --wellformedness-check --grounding-check --quote-check --pdf papers/garo_1.pdf

Every gate here is deterministic and LLM-free: the whole pass runs in about a
second over a few hundred rows. Two checks from the original design were
REMOVED on 2026-09-29, both recoverable from git history:

- The direction/ontology check (section 6.1 of that spec). Over the full
  303-row garo_1 dry run it flagged 0 rows and uniquely flagged 0: its
  curated lexicon covered 4 predicates against the 110 distinct predicates
  the corpus actually produced, and firing required the subject AND the
  object to look swapped simultaneously.
- The two-step LLM verify pass (section 5), along with the --verify /
  --verify-samples flags and the _reviewed_out.csv output. It was already
  opt-in, contributed no measured reduction in hallucination rate on this
  corpus beyond the deterministic gates, and cost 8+ hours of CPU-Ollama
  time on a single paper. If an LLM judge is wanted again, pruner/llm_judge.py
  is a live, separate implementation of the same idea.
"""

import argparse
import csv
from pathlib import Path

from eval.hallucination import load_page_texts
from verification.gate import apply_gates


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run(csv_path: str, run_wellformed: bool,
        run_grounding: bool = False, run_quote_check: bool = False,
        page_texts: dict[int, str] | None = None) -> dict:
    """Gate an extraction CSV and write the refined + per-gate flag files
    beside it. The gating itself lives in verification/gate.py, shared with
    main.py, so the offline numbers this produces and what the live pipeline
    enforces cannot drift apart."""
    rows = load_rows(csv_path)
    fieldnames = list(rows[0].keys()) if rows else ["subject", "predicate", "object"]

    outcome = apply_gates(
        rows,
        wellformedness=run_wellformed,
        grounding=run_grounding,
        quote=run_quote_check,
        page_texts=page_texts,
    )

    stem = Path(csv_path).stem
    out_dir = Path(csv_path).parent
    write_rows(out_dir / f"{stem}_refined.csv", fieldnames, outcome.kept)
    for gate_name, flagged_rows in outcome.flagged.items():
        write_rows(
            out_dir / f"{stem}_{gate_name}_flags.csv",
            fieldnames + ["flag_reason"],
            flagged_rows,
        )

    return outcome.counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the deterministic well-formedness/grounding/quote checks on an extraction CSV."
    )
    parser.add_argument("csv_path")
    parser.add_argument("--wellformedness-check", action="store_true")
    parser.add_argument(
        "--grounding-check", action="store_true",
        help="Flag (and hard-gate) any triple whose Subject/Object isn't textually "
             "present in its own sentence_ref. Deterministic, no LLM call.",
    )
    parser.add_argument(
        "--quote-check", action="store_true",
        help="Flag (and hard-gate) any triple whose sentence_ref isn't a genuine, "
             "verbatim quote from its own page of --pdf (catches a fabricated or "
             "blended citation wrapped around an otherwise-plausible claim). "
             "Deterministic, no LLM call. Requires --pdf.",
    )
    parser.add_argument(
        "--pdf",
        help="Path to the source PDF. Required by --quote-check, which checks each "
             "row's sentence_ref against its own page_number's text in this file.",
    )
    args = parser.parse_args()

    if args.quote_check and not args.pdf:
        parser.error("--quote-check requires --pdf")

    page_texts = load_page_texts(args.pdf) if args.pdf else None

    summary = run(
        args.csv_path, args.wellformedness_check,
        run_grounding=args.grounding_check,
        run_quote_check=args.quote_check, page_texts=page_texts,
    )
    print(summary)


if __name__ == "__main__":
    main()
