#!/usr/bin/env python3
"""
run_page_pipeline.py -- the real production pipeline (same steps as
main.py: extract -> chunk -> extract triples -> dedup -> validate ->
filter -> save CSV -> upload to Neo4j), scoped to a SINGLE PAGE of a PDF
instead of the whole document.

This is a new file, not an edit to main.py -- main.py has no page-scoping
option and is being left untouched, same as kg_extractor.py and
neo4j_loader/ have been throughout this project except for the one
explicitly-requested prompt change in kg_extractor.py. Every function
this script calls (chunk_text, extract_triples_from_chunk,
deduplicate_triples, save_triples_to_csv, validate_triple_format,
flag_artifact_triples, add_triples) is imported from the real modules,
completely unmodified -- the only thing different from main.py is the
text-extraction step, which pulls one page via pdfplumber instead of the
whole PDF via kg_extractor.extract_text_from_pdf().

Because kg_extractor.make_extraction_prompt() IS the production prompt
now (Variant A, round 4 refined -- see the comment above that function),
this script does NOT monkeypatch anything. It uses whatever
make_extraction_prompt() currently is, same as main.py would.

USAGE:
    python run_page_pipeline.py papers/garo_1.pdf 4
    python run_page_pipeline.py papers/garo_1.pdf 4 deepseek-r1:7b

WARNING: this uploads to the same live Neo4j (Aura) instance main.py
does -- there is no --dry-run here, same as main.py. If page 4 was
already included in a prior full-paper run, re-running it here will
MERGE onto those same existing relationships (subject+predicate+object
match) and refresh their properties, not create duplicates -- but if
this run's extraction produces even slightly different triples than last
time (the model isn't fully deterministic), the old ones that aren't
reproduced this run are NOT deleted; they'd just sit there unless
cleaned up separately. See the source_file/MERGE-collision discussion
from earlier in this project if that matters for what you're doing next.
"""

import sys
from pathlib import Path

import pdfplumber

import kg_extractor
from kg_extractor import chunk_text, extract_triples_from_chunk, deduplicate_triples, save_triples_to_csv
from Extraction_Check import validate_triple_format, flag_artifact_triples
from neo4j_loader.insert import add_triples
from subject_specificity import apply_subject_corrections, write_corrections_log


def extract_page_text(pdf_path: str, page_number: int) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        if page_number < 1 or page_number > len(pdf.pages):
            raise ValueError(f"Page {page_number} is out of range — {pdf_path} has {len(pdf.pages)} pages.")
        page = pdf.pages[page_number - 1]
        return page.extract_text() or ""


def main():
    if len(sys.argv) < 3:
        print("Usage: python run_page_pipeline.py <path_to_pdf> <page_number> [model_name]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    page_number = int(sys.argv[2])
    model = sys.argv[3] if len(sys.argv) > 3 else "deepseek-r1:7b"

    if not Path(pdf_path).exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    print(f"1. Extracting text from page {page_number} of {pdf_path} (pdfplumber)...")
    page_text = extract_page_text(pdf_path, page_number)
    if not page_text.strip():
        print("No extractable text on this page. Stopping.")
        sys.exit(0)
    print(f"   {len(page_text)} characters extracted.")

    wrapped = f"\n===== Page {page_number} =====\n{page_text}\n"

    print("2. Chunking text...")
    chunks = chunk_text(wrapped, chunk_size=1500, overlap=200)
    print(f"   Split into {len(chunks)} chunk(s).")

    print("3. Extracting triples with Ollama...")
    all_triples = []
    for idx, (chunk, page_num) in enumerate(chunks):
        print(f"Chunk {idx + 1}/{len(chunks)}...")
        triples = extract_triples_from_chunk(chunk, page_num, model)
        all_triples.extend(triples)

    print("4. Deduplicating...")
    triples = deduplicate_triples(all_triples)
    print(f"Extracted {len(triples)} unique triples.")

    if not triples:
        print("No triples extracted.")
        sys.exit(0)

    # Preserve the original PDF filename for source traceability -- same
    # field, same convention main.py uses.
    source_file = Path(pdf_path).name
    for triple in triples:
        triple["source_file"] = source_file

    # ------------------------------------------------------------
    # Validation gate: structural checks + artifact filtering, run
    # before anything reaches Neo4j -- identical to main.py's gate,
    # same imports, same functions, nothing duplicated or reimplemented.
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
    # Subject-specificity correction -- identical step to main.py's, same
    # shared function, nothing reimplemented. See subject_specificity.py
    # for the full rationale and the guards that keep this conservative.
    # ------------------------------------------------------------
    valid_triples, subject_corrections = apply_subject_corrections(valid_triples)
    if subject_corrections:
        print(f"\n[SUBJECT CORRECTION] Auto-corrected {len(subject_corrections)} triples away from the generic community subject:")
        for c in subject_corrections:
            print(f"  - {c['old_subject']} -> {c['new_subject']}   [{c['predicate']}]->({c['object']})")

    # Local backup CSV, written before the Neo4j upload -- distinct
    # filename from main.py's own output so a full-paper run and a
    # page-scoped run never overwrite each other.
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    paper_name = Path(pdf_path).stem
    csv_path = output_dir / f"{paper_name}_page{page_number}_kg.csv"
    save_triples_to_csv(valid_triples, str(csv_path), paper_name)
    print(f"Saved local backup to {csv_path}")

    if subject_corrections:
        corrections_path = output_dir / f"{paper_name}_page{page_number}_subject_corrections.csv"
        write_corrections_log(subject_corrections, str(corrections_path))
        print(f"Saved subject-correction log to {corrections_path}")

    add_triples(valid_triples)


if __name__ == "__main__":
    main()
