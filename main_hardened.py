#!/usr/bin/env python3
"""main_hardened.py -- the same end-to-end job as main.py (PDF -> extract ->
validate -> Neo4j), but with the extraction/verification harness's 5 hard
gates in place of main.py's own validate_triple_format() gate.

This is a NEW file, not an edit to main.py. main.py, kg_extractor.py, and
neo4j_loader/ are never modified -- main.py remains exactly as it is today,
runnable exactly as before, as a reference/backup of the pre-integration
pipeline. This script imports from all of them unmodified, the same
"never edit, only import" pattern already used by run_full_paper_variantA.py
and run_page_pipeline.py.

WHAT'S DIFFERENT FROM main.py
------------------------------
1. Prompt: swaps in the `extraction_broad_v2` prompt (prompts/extraction_broad_v2.txt)
   for the extraction step, in place of kg_extractor.py's built-in prompt.
   broad_v2 is the only one of the three prompts tested in this project
   (live/production, strict-tacit-only, broad_v2) that leaves ANY triples
   able to survive the hard gates below -- see the "Prompt A/B/C comparison"
   section of the results doc. Same on-disk-unmodified monkeypatch pattern
   run_full_paper_variantA.py already established.
2. Validation: replaces validate_triple_format() (UNKNOWN-placeholder +
   basic structural checks) and subject_specificity.py's auto-correction
   with run_verification_pipeline.py's 4 deterministic hard gates -- direction
   check, wellformedness check (incl. tautology), grounding check, and
   quote-genuineness check -- ON BY DEFAULT. These are free (no LLM call,
   seconds to run) and, on this project's own measured full-corpus results,
   already reached 0% real hallucination_rate on their own: the LLM verify
   pass (n=3 self-consistency, an Ollama call per sample) is now OPT-IN via
   --verify, since on a slow/loaded machine it can take many hours longer
   than extraction itself for no measured reduction in hallucination on this
   corpus -- see the results doc's "Hardening results" section (direction +
   wellformedness + grounding alone: 0% hallucination_rate, vs. 83% with
   grounding left out). Pass --verify to add it back for extra scrutiny at
   that cost. flag_artifact_triples() (research-methodology keyword
   filtering) is KEPT -- it's complementary, not redundant: it filters by
   topic (is this about the community or about the study itself), which
   none of the gates check. subject_specificity.py's auto-correction is
   DROPPED for now: it silently rewrites a triple's Subject rather than
   gating it, a different design principle than the hard-reject gates
   below, and wasn't in scope for this integration -- flag if you want it
   folded back in.
3. Neo4j: --dry-run (default) stops after writing the refined CSV and prints
   what WOULD be uploaded, without calling add_triples(). Pass --live to
   actually write to the configured Neo4j instance.

USAGE
-----
    python main_hardened.py papers/garo_1.pdf                  # dry run, deterministic gates only (fast)
    python main_hardened.py papers/garo_1.pdf --live            # real upload
    python main_hardened.py papers/garo_1.pdf --verify           # also run the slow LLM verify pass
    python main_hardened.py papers/garo_1.pdf deepseek-r1:7b --live
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import kg_extractor
from kg_extractor import run_kg_extraction, save_triples_to_csv
from Extraction_Check import flag_artifact_triples
from prompts.loader import load_prompt
from eval.hallucination import load_page_texts
from run_verification_pipeline import run as run_verification_gates


def _page_number_from_source_section(source_section: str) -> str:
    """kg_extractor.py's triples carry source_section='Page N' (a string),
    not a raw page_number column -- the harness's --quote-check needs an
    int-parseable page_number per row to look up that page's PDF text."""
    match = re.search(r"\d+", source_section or "")
    return match.group() if match else "0"


def save_triples_to_intermediate_csv(triples: list[dict], output_path: Path) -> None:
    """Like kg_extractor.save_triples_to_csv, but also carries source_file
    (Neo4j needs it) and page_number (the harness's gates need it)."""
    fieldnames = [
        "extraction_number", "paper", "subject", "predicate", "object",
        "source_section", "confidence", "passage", "sentence_ref",
        "source_file", "page_number",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, t in enumerate(triples, start=1):
            writer.writerow({
                "extraction_number": idx,
                "paper": t.get("paper", ""),
                "subject": t.get("subject", ""),
                "predicate": t.get("predicate", ""),
                "object": t.get("object", ""),
                "source_section": t.get("source_section", "Unknown"),
                "confidence": t.get("confidence", "Medium"),
                "passage": t.get("passage", ""),
                "sentence_ref": t.get("sentence_ref", ""),
                "source_file": t.get("source_file", ""),
                "page_number": _page_number_from_source_section(t.get("source_section", "")),
            })


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract a paper with broad_v2, run it through the 5 hard gates, then upload to Neo4j."
    )
    parser.add_argument("pdf_path")
    parser.add_argument("model", nargs="?", default="deepseek-r1:7b")
    parser.add_argument(
        "--live", action="store_true",
        help="Actually upload the kept triples to the configured Neo4j instance. "
             "Without this flag, stops after writing the refined CSV (dry run, default).",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Also run the LLM verify pass (Ollama, n=3 self-consistency by default). "
             "Off by default: the 4 deterministic gates alone already reached 0%% "
             "measured hallucination_rate on this project's full corpus, and the verify "
             "pass is by far the slowest, most expensive step (an Ollama call per sample, "
             "per surviving triple) for no measured safety gain on that corpus.",
    )
    parser.add_argument(
        "--verify-samples", type=int, default=3,
        help="Self-consistency resamples for the LLM verify pass, only used with --verify "
             "(default 3, matching the hardened configuration validated in this project's "
             "results doc).",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    # Swap in broad_v2 for the duration of this process only -- kg_extractor.py
    # is never edited on disk (same pattern as run_full_paper_variantA.py).
    kg_extractor.make_extraction_prompt = load_prompt("extraction_broad_v2")

    print(f"Prompt: extraction_broad_v2\nModel: {args.model}\nPDF: {pdf_path}\n")

    triples = run_kg_extraction(str(pdf_path), args.model)
    print(f"Extracted {len(triples)} raw candidate triples.")

    if not triples:
        print("No triples extracted. Nothing to do.")
        sys.exit(0)

    source_file = pdf_path.name
    paper_name = pdf_path.stem
    for t in triples:
        t["source_file"] = source_file
        t["paper"] = paper_name

    print("\nRunning artifact filter (research-methodology content, complementary to the hard gates)...")
    flagged = flag_artifact_triples(triples)
    if flagged:
        flagged_indices = {item["index"] for item in flagged}
        for item in flagged:
            t = item["triple"]
            print(f"  [FILTERED] ({t['subject']})-[{t['predicate']}]->({t['object']})  [matched: '{item['matched_keyword']}']")
        triples = [t for i, t in enumerate(triples) if i not in flagged_indices]
    print(f"Remaining after artifact filtering: {len(triples)}")

    if not triples:
        print("\nNo triples remained after artifact filtering. Skipping gates and upload.")
        sys.exit(0)

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    intermediate_csv = output_dir / f"{paper_name}_hardened_intermediate.csv"
    save_triples_to_intermediate_csv(triples, intermediate_csv)
    print(f"Saved intermediate (pre-gate) CSV to {intermediate_csv}")

    gate_names = "direction, wellformedness, grounding, quote-genuineness"
    if args.verify:
        gate_names += ", LLM verify (slow)"
    print(f"\nRunning the hard gates ({gate_names})...")
    page_texts = load_page_texts(str(pdf_path))
    summary = run_verification_gates(
        str(intermediate_csv),
        run_verify=args.verify, run_direction=True, run_wellformed=True,
        run_grounding=True, run_quote_check=True, page_texts=page_texts,
        verify_samples=args.verify_samples,
    )
    print(f"Gate summary: {summary}")

    refined_csv = output_dir / f"{paper_name}_hardened_intermediate_refined.csv"
    with open(refined_csv, newline="", encoding="utf-8") as f:
        kept_triples = list(csv.DictReader(f))

    print(f"\n{len(kept_triples)} triples survived every gate.")
    if not kept_triples:
        print("Nothing to upload.")
        sys.exit(0)

    if not args.live:
        print("\nDRY RUN (default) -- nothing uploaded. Kept triples:")
        for t in kept_triples:
            print(f"  ({t['subject']})-[{t['predicate']}]->({t['object']})  [{t.get('sentence_ref', '')[:80]}]")
        print(f"\nRe-run with --live to upload these {len(kept_triples)} triples to Neo4j.")
        sys.exit(0)

    from neo4j_loader.insert import add_triples
    add_triples(kept_triples)


if __name__ == "__main__":
    main()
