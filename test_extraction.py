#!/usr/bin/env python3
"""
test_extraction.py — standalone, read-only test harness for the KG
extraction pipeline's LLM extraction step.

WHY THIS EXISTS
----------------
main.py runs the full pipeline: PDF -> chunk_text() -> Ollama (DeepSeek R1
7B) -> parse_ollama_blocks() -> validation gate -> Neo4j upload. This script
lets you test the extraction step in isolation, on a single page, without
touching Neo4j at all, so you can inspect exactly what the model returns and
what the parser does with it.

It does NOT reimplement the prompt, the Ollama call, the chunking, or the
parser — it imports them directly, unmodified, from kg_extractor.py:

    - chunk_text            (same 1500-char / 200-char-overlap chunking)
    - extract_triples_from_chunk  (builds the prompt via make_extraction_prompt(),
                              calls Ollama, and parses the response via
                              parse_ollama_blocks() — all in one call, exactly
                              as run_kg_extraction() does per chunk)
    - deduplicate_triples   (same dedup logic used before Neo4j upload)

This script never imports neo4j_loader or config.py, and never calls
add_triples(). It is fully standalone and read-only with respect to the
existing pipeline files.

KNOWN BUG (see README "Known Issues" and Extraction_Check.py comments):
parse_ollama_blocks() splits the raw model text on the literal string
"\n// PASSAGE:" and then, per block, runs a single (non-global) regex search
for one "(Subject)-[PREDICATE]->(Object)" pattern. If DeepSeek R1 7B's
output doesn't open every block with that exact "// PASSAGE:" marker
(e.g. it wraps its answer in <think>...</think> reasoning first, drops the
"//", or otherwise drifts from the template), the split produces one giant
block instead of many, and the single non-global regex search only ever
recovers the FIRST triple in it — everything else in that block silently
becomes a single UNKNOWN/UNKNOWN/UNKNOWN placeholder instead of many real
triples. That is the "silently collapses to UNKNOWN" behavior. This script
does not fix that bug — it surfaces it: it reports how many of the
triples it got back are UNKNOWN, and extract_triples_from_chunk() (reused
unmodified) prints the raw model response for the first chunk it processes,
so you can see the mismatch directly.

USAGE
-----
    python test_extraction.py papers/garo_1.pdf 1
    python test_extraction.py papers/garo_1.pdf 1 --model deepseek-r1:7b
    python test_extraction.py papers/garo_1.pdf 1 --out-dir output

Requires the same Ollama endpoint as the rest of the pipeline (OLLAMA_URL in
.env, default http://localhost:11434/api/generate) to be reachable — i.e.
`docker compose up -d` (or `ollama serve`) must already be running.
"""

import argparse
import csv
import sys
from pathlib import Path

import pdfplumber

# --- Reused, unmodified, from the existing pipeline -------------------
# Nothing below is redefined or rewritten: same prompt, same Ollama call,
# same parser, same chunking, same dedup logic as main.py uses.
from kg_extractor import (
    OLLAMA_URL,
    chunk_text,
    extract_triples_from_chunk,
    deduplicate_triples,
)

# Optional: Extraction_Check.py's confidence mapping (High/Medium/Low -> a
# 0.0-1.0 float) is the closest thing this pipeline has to a numeric
# "confidence_score". Reused unmodified if available; parse_ollama_blocks()
# itself only ever emits the string labels "High" or "Low".
try:
    from Extraction_Check import normalize_confidence
except ImportError:
    normalize_confidence = None
# ------------------------------------------------------------------------


def extract_page_text(pdf_path: str, page_number: int) -> str:
    """Extract text from exactly one page (1-indexed) using pdfplumber —
    consistent with extract_text_from_pdf() in kg_extractor.py, but scoped
    to a single page instead of walking the whole document."""
    with pdfplumber.open(pdf_path) as pdf:
        if page_number < 1 or page_number > len(pdf.pages):
            raise ValueError(
                f"Page {page_number} is out of range — {pdf_path} has {len(pdf.pages)} pages."
            )
        page = pdf.pages[page_number - 1]
        return page.extract_text() or ""


def confidence_to_score(raw_confidence: str):
    """Map the parser's High/Low label to a numeric score using the
    pipeline's own Extraction_Check.normalize_confidence(), when available.
    Falls back to the raw label untouched otherwise."""
    if normalize_confidence is None:
        return raw_confidence
    try:
        return normalize_confidence(raw_confidence)
    except AssertionError:
        return raw_confidence


def main():
    parser = argparse.ArgumentParser(
        description="Test the KG extraction prompt/model/parser on a single PDF page. Does not touch Neo4j."
    )
    parser.add_argument("pdf_path", help="Path to the PDF, e.g. papers/garo_1.pdf")
    parser.add_argument("page_number", type=int, help="1-indexed page number to extract")
    parser.add_argument("--model", default="deepseek-r1:7b", help="Ollama model name (default: deepseek-r1:7b)")
    parser.add_argument("--out-dir", default="output", help="Directory to write the CSV into (default: output/)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    print(f"Ollama endpoint: {OLLAMA_URL}")
    print(f"Model: {args.model}")
    print(f"1. Extracting text from page {args.page_number} of {pdf_path.name} (pdfplumber)...")
    page_text = extract_page_text(str(pdf_path), args.page_number)

    if not page_text.strip():
        print(f"No extractable text on page {args.page_number} (scanned image? empty page?). Stopping.")
        sys.exit(0)

    print(f"   {len(page_text)} characters extracted.")

    # Wrap with the same "===== Page N =====" header chunk_text() expects,
    # so a page longer than chunk_size (1500 chars) gets split into the same
    # overlapping sub-chunks the full pipeline would produce for it.
    wrapped = f"\n===== Page {args.page_number} =====\n{page_text}\n"
    chunks = chunk_text(wrapped, chunk_size=1500, overlap=200)
    print(f"2. Split into {len(chunks)} chunk(s) (chunk_size=1500, overlap=200).")

    print("3. Running each chunk through the extraction prompt + Ollama call (kg_extractor.extract_triples_from_chunk)...")
    page_triples = []
    for i, (chunk, page_num) in enumerate(chunks, start=1):
        print(f"   Chunk {i}/{len(chunks)}...")
        page_triples.extend(extract_triples_from_chunk(chunk, page_num, args.model))

    print("4. Deduplicating (kg_extractor.deduplicate_triples)...")
    unique_triples = deduplicate_triples(page_triples)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)
    csv_path = out_dir / f"{pdf_path.stem}_page{args.page_number}_test.csv"

    unknown_count = 0
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["page_number", "subject", "predicate", "object", "confidence_score"])
        for t in unique_triples:
            if t.get("subject") == "UNKNOWN":
                unknown_count += 1
            writer.writerow([
                args.page_number,
                t.get("subject", ""),
                t.get("predicate", ""),
                t.get("object", ""),
                confidence_to_score(t.get("confidence", "")),
            ])

    print(f"5. Wrote {len(unique_triples)} triples to {csv_path}")

    if unknown_count:
        print(
            f"\n[WARNING] {unknown_count}/{len(unique_triples)} triples are UNKNOWN placeholders — "
            "this is the parse_ollama_blocks() block-format mismatch described at the top of this "
            "script and in README 'Known Issues'. Check the 'RAW LLM RESPONSE SAMPLE' printed above "
            "to see what DeepSeek actually returned vs. the expected '// PASSAGE:' block format."
        )

    print(
        f"\n=== Summary: page {args.page_number} of {pdf_path.name} -> "
        f"{len(unique_triples)} triples ({len(unique_triples) - unknown_count} parsed, "
        f"{unknown_count} UNKNOWN) ==="
    )


if __name__ == "__main__":
    main()
