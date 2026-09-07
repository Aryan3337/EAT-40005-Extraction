#!/usr/bin/env python3
"""
test_extraction_variants.py — run the same page-level extraction test as
test_extraction.py, but with a swapped-in PROMPT VARIANT, for A/B testing
prompt changes against kg_extractor.py's PR007 baseline.

Reuses chunk_text(), extract_triples_from_chunk(), deduplicate_triples(),
and OLLAMA_URL from kg_extractor.py completely unmodified. kg_extractor.py
is imported as a module (not `from kg_extractor import ...`) specifically so
that the one line below which does

    kg_extractor.make_extraction_prompt = <variant function>

actually takes effect: extract_triples_from_chunk() looks up
make_extraction_prompt by name inside the kg_extractor module's own
namespace every time it's called, so reassigning that name from here swaps
the prompt builder for the duration of this process only. kg_extractor.py
itself is never edited on disk, and main.py / neo4j_loader / config.py are
never imported or touched — this script cannot reach Neo4j.

Each variant is a full copy of the PR007 baseline prompt with exactly ONE
addition (see PROMPT_VARIANTS below), so any score difference is
attributable to that one change.

USAGE:
    python test_extraction_variants.py papers/garo_1.pdf 3 --variant baseline
    python test_extraction_variants.py papers/garo_1.pdf 3 --variant A
    python test_extraction_variants.py papers/garo_1.pdf 3 --variant B
    python test_extraction_variants.py papers/garo_1.pdf 3 --variant C
"""

import argparse
import csv
import sys
from pathlib import Path

import pdfplumber

import kg_extractor
from kg_extractor import OLLAMA_URL, chunk_text, extract_triples_from_chunk, deduplicate_triples

try:
    from Extraction_Check import normalize_confidence
except ImportError:
    normalize_confidence = None


# ============================================================
# Prompt variants — each is the PR007 baseline verbatim, plus ONE bullet.
# ============================================================

def _baseline_prompt(chunk_text: str) -> str:
    return f"""You are a knowledge graph extraction assistant. You will be provided with a passage from an academic research paper.

Read the passage. Identify every factual claim, relationship, practice, observation, or piece of knowledge about the Garo / Mandi community discussed in the passage.

For each meaningful piece, output a Cypher comment block in this exact format:

// PASSAGE: (Subject)-[PREDICATE]->(Object)
// SENTENCE REF: <exact sentence from the paper this was drawn from>
// SOURCE: <paper title placeholder>

Strict rules for the PASSAGE line:
- It MUST be written ONLY as (Subject)-[PREDICATE]->(Object). Never write a full sentence, paraphrase, or description on the PASSAGE line — that line is a structured triple, not prose.
- Subject and Object must be short noun phrases (1-4 words) in CamelCase with no spaces, e.g. (MandiLanguage), (GaroCommunity).
- Predicate must be UPPER_CASE_WITH_UNDERSCORES, e.g. IS_SPOKEN_BY, MAINTAINS, IS_LOCATED_IN.
- If a sentence lists multiple values for the same relationship (e.g. multiple professions, multiple locations, multiple languages), output ONE SEPARATE triple per value. Never combine multiple values into a single comma-separated Object — e.g. write (GaroCommunity)-[HAS_PROFESSION]->(Teacher) and (GaroCommunity)-[HAS_PROFESSION]->(Farmer) as two blocks, not one block with (Teacher, Farmer).
- Do not decide in advance what topics or domains to look for — extract everything factual the passage contains about the Garo/Mandi community's culture, language, history, practices, and lived experience.
- Each PASSAGE line must be traceable to a specific sentence, quoted exactly in SENTENCE REF. If you cannot find an exact sentence, do not output a block for that content at all.

Skip entirely — do not output a block for any of the following:
- Bibliographic references, author citations, journal titles, page numbers, or keyword lists.
- Descriptions of the research study itself: sample sizes, participant counts or demographics (age, gender), interview or data collection methods, data analysis or coding procedures, or any statement about what "the researchers" or "the study" did. Only extract facts about the Garo/Mandi community, never facts about how the paper studied them.

Output only the formatted comment blocks. No explanation, no prose, no extra text.

Passage:
{chunk_text}
"""


def _variant_a_prompt(chunk_text: str) -> str:
    return f"""You are a knowledge graph extraction assistant. You will be provided with a passage from an academic research paper.

Read the passage. Identify every factual claim, relationship, practice, observation, or piece of knowledge about the Garo / Mandi community discussed in the passage.

For each meaningful piece, output a Cypher comment block in this exact format:

// PASSAGE: (Subject)-[PREDICATE]->(Object)
// SENTENCE REF: <exact sentence from the paper this was drawn from>
// SOURCE: <paper title placeholder>

Strict rules for the PASSAGE line:
- It MUST be written ONLY as (Subject)-[PREDICATE]->(Object). Never write a full sentence, paraphrase, or description on the PASSAGE line — that line is a structured triple, not prose.
- Subject and Object must be short noun phrases (1-4 words) in CamelCase with no spaces, e.g. (MandiLanguage), (GaroCommunity).
- Always use the MOST SPECIFIC subject entity available in the sentence. If the sentence is about a specific subgroup, item, or role (e.g. GaroMen, GaroWomen, AttireStyles, GaroEducation), use that specific entity as the Subject — do not default to a broad community-level noun like GaroCommunity or MandiCommunity when a more specific one is stated or clearly implied.
- Predicate must be UPPER_CASE_WITH_UNDERSCORES, e.g. IS_SPOKEN_BY, MAINTAINS, IS_LOCATED_IN.
- If a sentence lists multiple values for the same relationship (e.g. multiple professions, multiple locations, multiple languages), output ONE SEPARATE triple per value. Never combine multiple values into a single comma-separated Object — e.g. write (GaroCommunity)-[HAS_PROFESSION]->(Teacher) and (GaroCommunity)-[HAS_PROFESSION]->(Farmer) as two blocks, not one block with (Teacher, Farmer).
- Do not decide in advance what topics or domains to look for — extract everything factual the passage contains about the Garo/Mandi community's culture, language, history, practices, and lived experience.
- Each PASSAGE line must be traceable to a specific sentence, quoted exactly in SENTENCE REF. If you cannot find an exact sentence, do not output a block for that content at all.

Skip entirely — do not output a block for any of the following:
- Bibliographic references, author citations, journal titles, page numbers, or keyword lists.
- Descriptions of the research study itself: sample sizes, participant counts or demographics (age, gender), interview or data collection methods, data analysis or coding procedures, or any statement about what "the researchers" or "the study" did. Only extract facts about the Garo/Mandi community, never facts about how the paper studied them.

Output only the formatted comment blocks. No explanation, no prose, no extra text.

Passage:
{chunk_text}
"""


def _variant_b_prompt(chunk_text: str) -> str:
    return f"""You are a knowledge graph extraction assistant. You will be provided with a passage from an academic research paper.

Read the passage. Identify every factual claim, relationship, practice, observation, or piece of knowledge about the Garo / Mandi community discussed in the passage.

For each meaningful piece, output a Cypher comment block in this exact format:

// PASSAGE: (Subject)-[PREDICATE]->(Object)
// SENTENCE REF: <exact sentence from the paper this was drawn from>
// SOURCE: <paper title placeholder>

Strict rules for the PASSAGE line:
- It MUST be written ONLY as (Subject)-[PREDICATE]->(Object). Never write a full sentence, paraphrase, or description on the PASSAGE line — that line is a structured triple, not prose.
- Subject and Object must be short noun phrases (1-4 words) in CamelCase with no spaces, e.g. (MandiLanguage), (GaroCommunity).
- Predicate must be UPPER_CASE_WITH_UNDERSCORES, e.g. IS_SPOKEN_BY, MAINTAINS, IS_LOCATED_IN.
- Reuse a single consistent predicate for a given relationship type across the whole passage (e.g. always WEARS for clothing — never invent variants like WEAR_MENS_ATTIRE or WEAR_WOMENS_ATTIRE for the same relationship). Before outputting a block, check whether the same Subject-Object pair or fact has already been extracted under a different predicate wording in this passage; if so, do not extract it again.
- If a sentence lists multiple values for the same relationship (e.g. multiple professions, multiple locations, multiple languages), output ONE SEPARATE triple per value. Never combine multiple values into a single comma-separated Object — e.g. write (GaroCommunity)-[HAS_PROFESSION]->(Teacher) and (GaroCommunity)-[HAS_PROFESSION]->(Farmer) as two blocks, not one block with (Teacher, Farmer).
- Do not decide in advance what topics or domains to look for — extract everything factual the passage contains about the Garo/Mandi community's culture, language, history, practices, and lived experience.
- Each PASSAGE line must be traceable to a specific sentence, quoted exactly in SENTENCE REF. If you cannot find an exact sentence, do not output a block for that content at all.

Skip entirely — do not output a block for any of the following:
- Bibliographic references, author citations, journal titles, page numbers, or keyword lists.
- Descriptions of the research study itself: sample sizes, participant counts or demographics (age, gender), interview or data collection methods, data analysis or coding procedures, or any statement about what "the researchers" or "the study" did. Only extract facts about the Garo/Mandi community, never facts about how the paper studied them.

Output only the formatted comment blocks. No explanation, no prose, no extra text.

Passage:
{chunk_text}
"""


def _variant_c_prompt(chunk_text: str) -> str:
    return f"""You are a knowledge graph extraction assistant. You will be provided with a passage from an academic research paper.

Read the passage. Identify every factual claim, relationship, practice, observation, or piece of knowledge about the Garo / Mandi community discussed in the passage.

For each meaningful piece, output a Cypher comment block in this exact format:

// PASSAGE: (Subject)-[PREDICATE]->(Object)
// SENTENCE REF: <exact sentence from the paper this was drawn from>
// SOURCE: <paper title placeholder>

Strict rules for the PASSAGE line:
- It MUST be written ONLY as (Subject)-[PREDICATE]->(Object). Never write a full sentence, paraphrase, or description on the PASSAGE line — that line is a structured triple, not prose.
- Subject and Object must be short noun phrases (1-4 words) in CamelCase with no spaces, e.g. (MandiLanguage), (GaroCommunity).
- Always use the MOST SPECIFIC subject entity available in the sentence. If the sentence is about a specific subgroup, item, or role (e.g. GaroMen, GaroWomen, AttireStyles, GaroEducation), use that specific entity as the Subject — do not default to a broad community-level noun like GaroCommunity or MandiCommunity when a more specific one is stated or clearly implied.
- Predicate must be UPPER_CASE_WITH_UNDERSCORES, e.g. IS_SPOKEN_BY, MAINTAINS, IS_LOCATED_IN.
- Reuse a single consistent predicate for a given relationship type across the whole passage (e.g. always WEARS for clothing — never invent variants like WEAR_MENS_ATTIRE or WEAR_WOMENS_ATTIRE for the same relationship). Before outputting a block, check whether the same Subject-Object pair or fact has already been extracted under a different predicate wording in this passage; if so, do not extract it again.
- If a sentence lists multiple values for the same relationship (e.g. multiple professions, multiple locations, multiple languages), output ONE SEPARATE triple per value. Never combine multiple values into a single comma-separated Object — e.g. write (GaroCommunity)-[HAS_PROFESSION]->(Teacher) and (GaroCommunity)-[HAS_PROFESSION]->(Farmer) as two blocks, not one block with (Teacher, Farmer).
- Do not decide in advance what topics or domains to look for — extract everything factual the passage contains about the Garo/Mandi community's culture, language, history, practices, and lived experience.
- Each PASSAGE line must be traceable to a specific sentence, quoted exactly in SENTENCE REF. If you cannot find an exact sentence, do not output a block for that content at all.

Skip entirely — do not output a block for any of the following:
- Bibliographic references, author citations, journal titles, page numbers, or keyword lists.
- Descriptions of the research study itself: sample sizes, participant counts or demographics (age, gender), interview or data collection methods, data analysis or coding procedures, or any statement about what "the researchers" or "the study" did. Only extract facts about the Garo/Mandi community, never facts about how the paper studied them.

Output only the formatted comment blocks. No explanation, no prose, no extra text.

Passage:
{chunk_text}
"""


PROMPT_VARIANTS = {
    "baseline": _baseline_prompt,
    "A": _variant_a_prompt,
    "B": _variant_b_prompt,
    "C": _variant_c_prompt,
}


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
    parser = argparse.ArgumentParser(description="Run a prompt variant test on a single PDF page. Does not touch Neo4j.")
    parser.add_argument("pdf_path")
    parser.add_argument("page_number", type=int)
    parser.add_argument("--variant", required=True, choices=list(PROMPT_VARIANTS.keys()))
    parser.add_argument("--model", default="deepseek-r1:7b")
    parser.add_argument("--out-dir", default="output")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    # Swap in the variant's prompt builder. extract_triples_from_chunk() (imported
    # above, unmodified) calls make_extraction_prompt(chunk_text) by looking that
    # name up inside the kg_extractor module namespace each time -- so this
    # reassignment is picked up without touching kg_extractor.py on disk.
    kg_extractor.make_extraction_prompt = PROMPT_VARIANTS[args.variant]

    print(f"Variant: {args.variant}")
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

    print(f"3. Running each chunk through variant '{args.variant}' prompt + Ollama...")
    page_triples = []
    for i, (chunk, page_num) in enumerate(chunks, start=1):
        print(f"   Chunk {i}/{len(chunks)}...")
        page_triples.extend(extract_triples_from_chunk(chunk, page_num, args.model))

    print("4. Deduplicating...")
    unique_triples = deduplicate_triples(page_triples)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)
    csv_path = out_dir / f"{pdf_path.stem}_page{args.page_number}_variant{args.variant}.csv"

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
        print(f"[WARNING] {unknown_count}/{len(unique_triples)} triples are UNKNOWN placeholders (parser format mismatch).")
    print(f"\n=== Summary: variant {args.variant}, page {args.page_number} -> {len(unique_triples)} triples ({len(unique_triples)-unknown_count} parsed, {unknown_count} UNKNOWN) ===")


if __name__ == "__main__":
    main()
