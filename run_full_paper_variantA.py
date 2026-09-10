#!/usr/bin/env python3
"""
run_full_paper_variantA.py — run kg_extractor.py's real, unmodified full-paper
pipeline (run_kg_extraction) across EVERY page of a PDF, with Variant A's
round-4 "refined" prompt monkeypatched in instead of the PR007 baseline.

--- WHY VARIANT A (round 4) WAS CHOSEN ---
Across the 4 rounds of page-3 testing logged in Prompt_Iteration_Log.xlsx, no
single variant was clearly "best" by peak score alone — Variant C's round-3
prompt hit the highest strict-match score ever recorded (13/23), but the SAME
underlying prompt, refined further in round 4 (combining Variant A's and
Variant B's fixes), collapsed to 1/23. That is too large a swing on an
identical instruction to trust for a first full-paper run.

Variant A's round-4 prompt was picked instead because its scores across all 4
rounds — 6, 2, 4, 8 (TP Strict, out of 23) — trended upward and had much lower
run-to-run variance (stdev ≈ 2.2) than Variant C (8, 7, 13, 1 — stdev ≈ 4.3)
or the baseline (11, 2, 2, 2 — stdev ≈ 3.9). Its round-4 result (8/23) is also
its best-ever score, and the specific change behind it — "choose the Subject
at the level of specificity the sentence itself actually supports" instead of
a blanket "always prefer specific" rule — was itself derived from reading the
full 148-triple manual ground truth (not just page 3), so it was designed to
generalize rather than overfit to one page. That combination (best own score,
lowest noise, evidence-based fix) made it the safer choice for a full-paper
run where there's much less ground truth to fall back on.

--- HOW THIS SCRIPT AVOIDS TOUCHING RESTRICTED FILES ---
kg_extractor.py, main.py, and neo4j_loader/ are NEVER edited on disk and
neo4j_loader is NEVER imported — this script cannot reach Neo4j, full stop.

Like test_extraction_variants.py, kg_extractor is imported as a MODULE (not
`from kg_extractor import make_extraction_prompt`), so that reassigning
`kg_extractor.make_extraction_prompt` actually takes effect: every internal
call site in kg_extractor.py (inside extract_triples_from_chunk) looks the
name up in the module's own namespace each time it runs, so the swap applies
for the duration of this process only, with zero changes to the file on disk.

Everything else — extract_text_from_pdf, chunk_text, extract_triples_from_chunk,
deduplicate_triples, save_triples_to_csv, and the overall run_kg_extraction
orchestration — is kg_extractor.py's own real code, completely unmodified.
This is a genuine full-document run across every page (chunk_text() already
processes the whole extracted text, not a single page), not a page-3 test.

The validation gate (validate_triple_format + flag_artifact_triples, from
Extraction_Check.py) is applied before saving, exactly as main.py does, so the
output CSV reflects what would actually reach Neo4j — it just stops one step
short of calling add_triples(), so nothing is written to any database.

USAGE:
    python run_full_paper_variantA.py papers/garo_1.pdf
    python run_full_paper_variantA.py papers/garo_1.pdf deepseek-r1:7b
"""

import sys
from pathlib import Path

import kg_extractor
from kg_extractor import run_kg_extraction, save_triples_to_csv
from Extraction_Check import validate_triple_format, flag_artifact_triples


def _variant_a_prompt(chunk_text: str) -> str:
    return f"""You are a knowledge graph extraction assistant. You will be provided with a passage from an academic research paper.

Read the passage. Identify every factual claim, relationship, practice, belief, observation, or piece of knowledge about the Garo / Mandi community discussed in the passage. This passage may come from any part of the paper -- introduction, demographics, attire, food, religion, festivals, health, household life, occupation, or any other section -- so do not assume in advance which topic it covers.

Output your answer immediately as a sequence of Cypher comment blocks. Do not include any reasoning, planning, or <think> content, and do not write anything before the first block -- your entire response must consist only of comment blocks in this exact format:

// PASSAGE: (Subject)-[PREDICATE]->(Object)
// SENTENCE REF: <exact sentence from the paper this was drawn from>
// SOURCE: <paper title placeholder>

Strict rules for the PASSAGE line:
- It MUST be written ONLY as (Subject)-[PREDICATE]->(Object). Never write a full sentence, paraphrase, or description on the PASSAGE line -- that line is a structured triple, not prose.
- Subject and Object must be short noun phrases (1-4 words) in CamelCase with no spaces, e.g. (MandiLanguage), (GaroCommunity).
- Predicate must be UPPER_CASE_WITH_UNDERSCORES ONLY -- no lowercase letters, no spaces, no mixed case. For example, write IS_USED_IN, never "IS USED IN"; write WEARS, never "WE WEAR"; write HAS_FAMILY_STRUCTURE, never "HAS_FamilyStructure". A predicate containing a space or a lowercase word is always wrong -- rewrite it before outputting the block.
- Choose the Subject at the level of specificity the sentence itself actually supports -- neither more nor less. If the sentence names a specific subgroup, item, individual, organization, ritual, or role, use that specific entity as the Subject. If the sentence instead makes a general statement about the community as a whole, GaroPeople or GaroCommunity IS the correct Subject -- do not force a narrower entity onto a general statement, and do not default to a broad community-level noun when the sentence clearly names something narrower.
- If a sentence lists multiple values for the same relationship (e.g. multiple professions, locations, languages, foods, or beliefs), output ONE SEPARATE triple per value. Never combine multiple values into a single comma-separated Object -- e.g. write (GaroCommunity)-[HAS_PROFESSION]->(Teacher) and (GaroCommunity)-[HAS_PROFESSION]->(Farmer) as two blocks, not one block with (Teacher, Farmer). If you decide not to extract something because it is a duplicate, simply skip it -- never bundle it into another block instead.
- Do not decide in advance what topics or domains to look for -- extract everything factual the passage contains about the Garo/Mandi community's culture, language, history, beliefs, practices, and lived experience, whatever section of the paper it comes from.
- Each PASSAGE line must be traceable to a specific sentence, quoted exactly in SENTENCE REF. If you cannot find an exact sentence, do not output a block for that content at all.

Skip entirely -- do not output a block for any of the following:
- Bibliographic references, author citations, journal titles, page numbers, or keyword lists.
- Anything describing the research process itself rather than the community: sample sizes, participant/respondent counts or demographics, what participants or respondents were asked, told, or observed to say, how they were classified or coded (e.g. classification schemes, occupational codes), interview or data collection methods, data analysis procedures, or any subjective assessment the researchers made about participants (e.g. calling them vulnerable, hesitant, willing, or reluctant). "Respondents" or "participants" must never appear as a Subject or Object. Only extract facts about the Garo/Mandi community itself, never facts about how the paper studied them or who was surveyed.

Output only the formatted comment blocks. No explanation, no prose, no extra text, and nothing before the first "// PASSAGE:" line.

Passage:
{chunk_text}
"""


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_full_paper_variantA.py <path_to_pdf> [model_name]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else "deepseek-r1:7b"

    if not Path(pdf_path).exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    # Swap in Variant A's round-4 refined prompt. See module docstring for why
    # this is safe: kg_extractor.py is never edited on disk.
    kg_extractor.make_extraction_prompt = _variant_a_prompt

    print("Prompt: Variant A (round 4, refined)")
    print(f"Model: {model}")
    print(f"PDF: {pdf_path}\n")

    triples = run_kg_extraction(pdf_path, model)

    print(f"\nExtracted {len(triples)} unique triples across the whole paper.")

    if not triples:
        print("No triples extracted. Nothing to save.")
        sys.exit(0)

    source_file = Path(pdf_path).name
    for t in triples:
        t["source_file"] = source_file

    # Same validation gate main.py runs before add_triples() -- reused
    # as-is, imported, never modified. This script simply never calls
    # add_triples() itself, so nothing reaches Neo4j.
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
        print("\nNo valid triples remained after validation and filtering. Nothing to save.")
        sys.exit(0)

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    paper_name = Path(pdf_path).stem
    csv_path = output_dir / f"{paper_name}_fullpaper_variantA.csv"
    save_triples_to_csv(valid_triples, str(csv_path), paper_name)

    unknown_count = sum(1 for t in valid_triples if t.get("subject") == "UNKNOWN")
    print(f"\nSaved {len(valid_triples)} triples to {csv_path}")
    if unknown_count:
        print(f"[WARNING] {unknown_count}/{len(valid_triples)} triples are UNKNOWN placeholders (parser format mismatch).")
    print("\n(This script stops here -- it never imports neo4j_loader and never calls add_triples(), so nothing was uploaded to Neo4j.)")


if __name__ == "__main__":
    main()
