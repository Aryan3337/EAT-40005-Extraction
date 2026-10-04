import argparse
import csv
import sys
from pathlib import Path

from eval.hallucination import load_page_texts
from kg_extractor import run_kg_extraction, save_triples_to_csv
from neo4j_loader.insert import add_triples
from Extraction_Check import validate_triple_format, flag_artifact_triples
from subject_specificity import apply_subject_corrections, write_corrections_log
from verification.gate import apply_gates, page_number_from_source_section

# The refined/flag CSVs carry two columns the plain extraction CSV doesn't:
# source_file (Neo4j needs it) and page_number (the quote gate needs it).
GATE_CSV_FIELDS = [
    "extraction_number", "paper", "subject", "predicate", "object",
    "source_section", "confidence", "passage", "sentence_ref",
    "source_file", "page_number",
]


def write_gate_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


parser = argparse.ArgumentParser(
    description="Extract a paper into triples, gate them, and upload to Neo4j."
)
parser.add_argument("pdf_path")
parser.add_argument("model", nargs="?", default="deepseek-r1:7b")
parser.add_argument(
    "--no-gates", action="store_true",
    help="Skip the three deterministic verification gates (well-formedness, "
         "grounding, quote-genuineness) and upload everything that clears the "
         "older structural checks, as this script did before the gates were "
         "wired in. They are deterministic and LLM-free, costing about a "
         "second per few hundred rows, so there is rarely a reason to.",
)
parser.add_argument(
    "--dry-run", action="store_true",
    help="Do everything except the Neo4j upload. The CSVs are still written.",
)
args = parser.parse_args()

pdf_path = args.pdf_path
model = args.model

if not Path(pdf_path).exists():
    print(f"File not found: {pdf_path}")
    sys.exit(1)

triples = run_kg_extraction(pdf_path, model)

print(f"Extracted {len(triples)} triples.")

if triples:
    # Preserve the original PDF filename for source traceability
    source_file = Path(pdf_path).name

    for triple in triples:
        triple["source_file"] = source_file

    # ------------------------------------------------------------
    # Validation gate: structural checks + artifact filtering,
    # run before anything reaches Neo4j.
    # ------------------------------------------------------------
    print("\nRunning validation gate...")
    valid_triples = []
    rejected_count = 0

    for triple in triples:
        try:
            validate_triple_format(triple)
            valid_triples.append(triple)
        except AssertionError as e:
            rejected_count += 1
            print(f"  [REJECTED] {triple.get('subject', '?')}: {e}")

    print(f"Validation: {len(valid_triples)} passed, {rejected_count} rejected.")

    # Artifact filtering: exclude research-methodology triples entirely
    # rather than just warning, since they aren't real community knowledge.
    flagged = flag_artifact_triples(valid_triples)
    if flagged:
        flagged_indices = {item['index'] for item in flagged}
        print(f"\n[FILTERED] Excluding {len(flagged)} triples that matched research-methodology artifacts:")
        for item in flagged:
            t = item['triple']
            print(f"  - ({t['subject']})-[{t['predicate']}]->({t['object']})  [matched: '{item['matched_keyword']}']")
        valid_triples = [t for i, t in enumerate(valid_triples) if i not in flagged_indices]
        print(f"Remaining after artifact filtering: {len(valid_triples)}")

    if not valid_triples:
        print("\nNo valid triples remained after validation and filtering. Skipping save and upload.")
        sys.exit(0)

    # ------------------------------------------------------------
    # Subject-specificity correction: automatically rewrites a triple's
    # Subject away from the generic GaroCommunity/GaroPeople node when its
    # source sentence names something more specific (a house, a household,
    # a diet...), using a deterministic dependency-parse check rather than
    # relying on the model to follow that rule itself -- see
    # subject_specificity.py for the full rationale and the guards that
    # keep this conservative (attribution phrases and meta/abstract
    # candidates like "the passage" are never auto-applied). Fully
    # automatic, no manual review step -- every correction actually made is
    # logged to output/{paper}_subject_corrections.csv for auditability.
    #
    # This runs BEFORE the verification gates on purpose. The corrected
    # Subject is a noun chunk taken from the triple's own sentence_ref, so
    # correcting first moves a Subject towards the citation's wording, which
    # is exactly what the grounding gate then checks for.
    # ------------------------------------------------------------
    valid_triples, subject_corrections = apply_subject_corrections(valid_triples)
    if subject_corrections:
        print(f"\n[SUBJECT CORRECTION] Auto-corrected {len(subject_corrections)} triples away from the generic community subject:")
        for c in subject_corrections:
            print(f"  - {c['old_subject']} -> {c['new_subject']}   [{c['predicate']}]->({c['object']})")

    # Local backup CSV, written before the Neo4j upload so results are on
    # disk even if the upload fails partway through. This is the FULL
    # pre-gate set: the gates write their own refined/flag files below, so
    # nothing that was extracted is lost from disk by gating.
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    paper_name = Path(pdf_path).stem
    csv_path = output_dir / f"{paper_name}_kg.csv"
    save_triples_to_csv(valid_triples, str(csv_path), paper_name)
    print(f"Saved local backup to {csv_path}")

    if subject_corrections:
        corrections_path = output_dir / f"{paper_name}_subject_corrections.csv"
        write_corrections_log(subject_corrections, str(corrections_path))
        print(f"Saved subject-correction log to {corrections_path}")

    # ------------------------------------------------------------
    # Verification gates: well-formedness, grounding and quote-genuineness
    # (see verification/gate.py). Deterministic and LLM-free. These are a
    # HARD gate -- a flagged triple is dropped, not held for review, because
    # this graph feeds a fully autonomous chatbot with no human in the loop.
    # Expect a steep drop in volume: on the measured garo_1 corpus roughly
    # 300 extracted triples come out as 13. That is the intended trade --
    # precision over recall, since a wrong fact reaches an end user directly
    # while a missed one only means the chatbot knows slightly less.
    # ------------------------------------------------------------
    if args.no_gates:
        print("\n[GATES SKIPPED] --no-gates: uploading everything that cleared the structural checks.")
        uploadable = valid_triples
    else:
        print("\nRunning verification gates...")
        for idx, t in enumerate(valid_triples, start=1):
            t.setdefault("paper", paper_name)
            t["extraction_number"] = idx
            t["page_number"] = page_number_from_source_section(t.get("source_section", ""))

        outcome = apply_gates(
            valid_triples,
            page_texts=load_page_texts(pdf_path),
            quote=True,
        )

        counts = outcome.counts
        print(f"Gates: {counts['refined']} of {len(valid_triples)} triples survived "
              f"(well-formedness flagged {counts['wellformedness_flags']}, "
              f"grounding {counts['grounding_flags']}, "
              f"quote-genuineness {counts['quote_flags']}; "
              f"a triple can be flagged by more than one).")

        refined_path = output_dir / f"{paper_name}_kg_refined.csv"
        write_gate_csv(refined_path, GATE_CSV_FIELDS, outcome.kept)
        print(f"Saved gated triples to {refined_path}")

        for gate_name, flagged_rows in outcome.flagged.items():
            flag_path = output_dir / f"{paper_name}_kg_{gate_name}_flags.csv"
            write_gate_csv(flag_path, GATE_CSV_FIELDS + ["flag_reason"], flagged_rows)
            print(f"  {len(flagged_rows)} {gate_name} rejections -> {flag_path}")

        uploadable = outcome.kept

    if not uploadable:
        print("\nNo triples survived the verification gates. Nothing to upload.")
        sys.exit(0)

    if args.dry_run:
        print(f"\n[DRY RUN] Would upload {len(uploadable)} triples to Neo4j. Nothing was sent.")
    else:
        add_triples(uploadable)
else:
    print("No triples extracted.")
