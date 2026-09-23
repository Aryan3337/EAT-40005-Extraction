#!/usr/bin/env python3
"""
test_extraction_prompt_config.py -- run a single PDF page through one of the
versioned prompt files in prompts/ (loaded via prompts.loader.load_prompt),
for the "(B) strict tacit-only" / "(C) broad-v2 + verify" comparison
described in README "Comparing extraction/verification configurations".

Same reuse pattern as test_extraction_variants.py: chunk_text(),
extract_triples_from_chunk(), deduplicate_triples(), and OLLAMA_URL are
imported unmodified from kg_extractor.py, and kg_extractor.make_extraction_prompt
is swapped for the duration of this process only via module-attribute
reassignment (kg_extractor.py is never edited on disk).

Unlike test_extraction_variants.py, this script's output CSV includes a
sentence_ref column (the model's own "// SENTENCE REF:" line, preserved
verbatim by kg_extractor.parse_ollama_blocks()) -- required because this
output may be fed to `run_verification_pipeline.py --verify`, which judges
each triple against its sentence_ref (see that script's shape check).

USAGE:
    python test_extraction_prompt_config.py papers/garo_1.pdf 3 --prompt extraction_strict_tacit_v1
    python test_extraction_prompt_config.py papers/garo_1.pdf 3 --prompt extraction_broad_v2
"""

import argparse
import csv
import sys
from pathlib import Path

import pdfplumber

import kg_extractor
from kg_extractor import OLLAMA_URL, chunk_text, extract_triples_from_chunk, deduplicate_triples
from prompts.loader import load_prompt

try:
    from Extraction_Check import normalize_confidence
except ImportError:
    normalize_confidence = None


def extract_page_text(pdf_path: str, page_number: int) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        if page_number < 1 or page_number > len(pdf.pages):
            raise ValueError(f"Page {page_number} is out of range — {pdf_path} has {len(pdf.pages)} pages.")
        page = pdf.pages[page_number - 1]
        return page.extract_text() or ""


def confidence_to_score(raw_confidence: str):
    if normalize_confidence is None:
        return raw_confidence
    try:
        return normalize_confidence(raw_confidence)
    except AssertionError:
        return raw_confidence


def main():
    parser = argparse.ArgumentParser(
        description="Run a versioned prompts/ template on a single PDF page. Does not touch Neo4j."
    )
    parser.add_argument("pdf_path")
    parser.add_argument("page_number", type=int)
    parser.add_argument("--prompt", required=True, help="prompts/<name>.txt, e.g. extraction_strict_tacit_v1")
    parser.add_argument("--model", default="deepseek-r1:7b")
    parser.add_argument("--out-dir", default="output")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    # extract_triples_from_chunk() looks up make_extraction_prompt by name
    # inside the kg_extractor module namespace each call, so this
    # reassignment is picked up without touching kg_extractor.py on disk.
    kg_extractor.make_extraction_prompt = load_prompt(args.prompt)

    print(f"Prompt: {args.prompt}")
    print(f"Ollama endpoint: {OLLAMA_URL}")
    print(f"Model: {args.model}")
    print(f"1. Extracting text from page {args.page_number} of {pdf_path.name} (pdfplumber)...")
    page_text = extract_page_text(str(pdf_path), args.page_number)
    if not page_text.strip():
        print("No extractable text on this page. Stopping.")
        sys.exit(0)
    print(f"   {len(page_text)} characters extracted.")

    wrapped = f"\n===== Page {args.page_number} =====\n{page_text}\n"
    chunks = chunk_text(wrapped, chunk_size=1500, overlap=200)
    print(f"2. Split into {len(chunks)} chunk(s).")

    print(f"3. Running each chunk through prompt '{args.prompt}' + Ollama...")
    page_triples = []
    for i, (chunk, page_num) in enumerate(chunks, start=1):
        print(f"   Chunk {i}/{len(chunks)}...")
        page_triples.extend(extract_triples_from_chunk(chunk, page_num, args.model))

    print("4. Deduplicating...")
    unique_triples = deduplicate_triples(page_triples)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)
    csv_path = out_dir / f"{pdf_path.stem}_page{args.page_number}_{args.prompt}.csv"

    unknown_count = 0
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["page_number", "subject", "predicate", "object", "confidence_score", "sentence_ref"])
        for t in unique_triples:
            if t.get("subject") == "UNKNOWN":
                unknown_count += 1
            writer.writerow([
                args.page_number,
                t.get("subject", ""),
                t.get("predicate", ""),
                t.get("object", ""),
                confidence_to_score(t.get("confidence", "")),
                t.get("sentence_ref", ""),
            ])

    print(f"5. Wrote {len(unique_triples)} triples to {csv_path}")
    if unknown_count:
        print(f"[WARNING] {unknown_count}/{len(unique_triples)} triples are UNKNOWN placeholders (parser format mismatch).")
    print(f"\n=== Summary: prompt {args.prompt}, page {args.page_number} -> {len(unique_triples)} triples ({len(unique_triples)-unknown_count} parsed, {unknown_count} UNKNOWN) ===")


if __name__ == "__main__":
    main()
