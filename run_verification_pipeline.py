#!/usr/bin/env python3
"""Takes an already-produced extraction CSV and optionally runs the verify
pass, direction check, and/or well-formedness check on it. Never imports
neo4j_loader, never calls add_triples(). See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §7.5.

    python run_verification_pipeline.py output/garo_1_page3_variantA.csv \\
        --direction-check --wellformedness-check --verify
"""

import argparse
import csv
from pathlib import Path

from verification.direction_check import check_direction
from verification.verify_pass import JudgeFn, judge_with_ollama, verify_triple
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


def run(csv_path: str, run_verify: bool, run_direction: bool, run_wellformed: bool,
        judge_fn: JudgeFn = judge_with_ollama) -> dict:
    rows = load_rows(csv_path)
    fieldnames = list(rows[0].keys()) if rows else ["subject", "predicate", "object"]

    refined: list[dict] = []
    reviewed_out: list[dict] = []
    direction_flags: list[dict] = []
    wellformedness_flags: list[dict] = []

    for row in rows:
        subject, predicate, obj = row["subject"], row["predicate"], row["object"]

        if run_direction:
            direction_result = check_direction(subject, predicate, obj)
            if direction_result.flagged:
                flagged_row = dict(row)
                flagged_row["flag_reason"] = direction_result.reason or ""
                direction_flags.append(flagged_row)

        if run_wellformed:
            wellformedness_result = check_wellformedness(subject, predicate, obj)
            if wellformedness_result.flagged:
                flagged_row = dict(row)
                flagged_row["flag_reason"] = "; ".join(wellformedness_result.reasons)
                wellformedness_flags.append(flagged_row)

        if run_verify:
            result = verify_triple(subject, predicate, obj, _sentence_for_row(row), judge_fn)
            if result.band == "keep":
                refined.append(row)
            elif result.band == "review":
                reviewed_row = dict(row)
                reviewed_row["verify_reason"] = result.reason
                reviewed_row["verify_confidence"] = result.confidence
                reviewed_out.append(reviewed_row)
            # "reject" band: dropped, not written anywhere -- same as main.py's
            # existing validation gate, rejection is implicit via absence.
        else:
            refined.append(row)

    stem = Path(csv_path).stem
    out_dir = Path(csv_path).parent
    write_rows(out_dir / f"{stem}_refined.csv", fieldnames, refined)
    if reviewed_out:
        write_rows(
            out_dir / f"{stem}_reviewed_out.csv",
            fieldnames + ["verify_reason", "verify_confidence"], reviewed_out,
        )
    if direction_flags:
        write_rows(out_dir / f"{stem}_direction_flags.csv", fieldnames + ["flag_reason"], direction_flags)
    if wellformedness_flags:
        write_rows(out_dir / f"{stem}_wellformedness_flags.csv", fieldnames + ["flag_reason"], wellformedness_flags)

    return {
        "refined": len(refined),
        "reviewed_out": len(reviewed_out),
        "direction_flags": len(direction_flags),
        "wellformedness_flags": len(wellformedness_flags),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run verification/direction/well-formedness checks on an extraction CSV."
    )
    parser.add_argument("csv_path")
    parser.add_argument("--verify", action="store_true", help="Run the LLM verify pass (requires Ollama).")
    parser.add_argument("--direction-check", action="store_true")
    parser.add_argument("--wellformedness-check", action="store_true")
    args = parser.parse_args()

    summary = run(args.csv_path, args.verify, args.direction_check, args.wellformedness_check)
    print(summary)


if __name__ == "__main__":
    main()
