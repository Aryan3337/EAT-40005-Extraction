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
from verification.grounding_check import check_grounding
from verification.quote_check import check_quote_genuine
from verification.wellformedness_check import check_wellformedness


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _sentence_for_row(row: dict) -> str:
    return row.get("sentence_ref") or row.get("passage") or ""


def write_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run(csv_path: str, run_wellformed: bool,
        run_grounding: bool = False, run_quote_check: bool = False,
        page_texts: dict[int, str] | None = None) -> dict:
    if run_quote_check and page_texts is None:
        raise ValueError(
            "--quote-check requires page_texts (pass --pdf on the CLI, or "
            "page_texts= when calling run() directly) -- it checks each "
            "row's sentence_ref against its own page of the source PDF."
        )

    rows = load_rows(csv_path)
    fieldnames = list(rows[0].keys()) if rows else ["subject", "predicate", "object"]

    refined: list[dict] = []
    wellformedness_flags: list[dict] = []
    grounding_flags: list[dict] = []
    quote_flags: list[dict] = []

    for row in rows:
        subject, predicate, obj = row["subject"], row["predicate"], row["object"]

        hard_gated = False

        if run_wellformed:
            wellformedness_result = check_wellformedness(subject, predicate, obj)
            if wellformedness_result.flagged:
                hard_gated = True
                flagged_row = dict(row)
                flagged_row["flag_reason"] = "; ".join(wellformedness_result.reasons)
                wellformedness_flags.append(flagged_row)

        if run_grounding:
            grounding_result = check_grounding(subject, obj, _sentence_for_row(row))
            if grounding_result.flagged:
                hard_gated = True
                flagged_row = dict(row)
                flagged_row["flag_reason"] = "; ".join(grounding_result.reasons)
                grounding_flags.append(flagged_row)

        if run_quote_check:
            page_text = page_texts.get(int(row["page_number"]), "") if page_texts else ""
            quote_result = check_quote_genuine(_sentence_for_row(row), page_text)
            if quote_result.flagged:
                hard_gated = True
                flagged_row = dict(row)
                flagged_row["flag_reason"] = "; ".join(quote_result.reasons)
                quote_flags.append(flagged_row)

        # These checks are a hard gate on refined, not just an audit-trail
        # side channel: this pipeline feeds a fully autonomous chatbot with
        # no human review step, so a flagged row must never reach refined.
        # Rejection is implicit via absence from refined, and every rejected
        # row is recorded in the flag file of whichever gate caught it.
        if not hard_gated:
            refined.append(row)

    stem = Path(csv_path).stem
    out_dir = Path(csv_path).parent
    write_rows(out_dir / f"{stem}_refined.csv", fieldnames, refined)
    if wellformedness_flags:
        write_rows(out_dir / f"{stem}_wellformedness_flags.csv", fieldnames + ["flag_reason"], wellformedness_flags)
    if grounding_flags:
        write_rows(out_dir / f"{stem}_grounding_flags.csv", fieldnames + ["flag_reason"], grounding_flags)
    if quote_flags:
        write_rows(out_dir / f"{stem}_quote_flags.csv", fieldnames + ["flag_reason"], quote_flags)

    return {
        "refined": len(refined),
        "wellformedness_flags": len(wellformedness_flags),
        "grounding_flags": len(grounding_flags),
        "quote_flags": len(quote_flags),
    }


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
