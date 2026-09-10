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

Each variant is a full copy of a shared base prompt with exactly ONE
addition on top (see PROMPT_VARIANTS below), so any score difference between
baseline/A/B/C is attributable to that one change.

--- REVISION HISTORY ---
Round 1-3: baseline/A/B/C used kg_extractor.py's original PR007 wording as
the shared base (A added a "prefer specific subject" bullet, B added a
"consistent predicate" bullet, C added both).

Round 4 (this revision): baseline/A/B/C were all rewritten, based on what
every prompt -- not just one variant -- kept failing on across all 3 rounds:
  1. Format non-compliance: baseline's own real output routinely broke its
     own "UPPER_CASE_WITH_UNDERSCORES" rule ("WE WEAR", "IS USED IN",
     "HAS_FamilyStructure") -- the rule existed but wasn't landing. Added
     explicit bad-vs-good examples to make it unambiguous, in all 4.
  2. The parse_ollama_blocks() UNKNOWN-placeholder bug (reasoning/<think>
     text before the first "// PASSAGE:" marker) hit every variant at least
     once. Added an explicit "no reasoning, nothing before the first block"
     instruction to all 4.
  3. The study-methodology leak evolved past a literal "Respondents" keyword
     into paraphrases (ASKED_ABOUT_X, HAVE-demographic information,
     ISCO_YIELDED-style classification jargon) in every round, for every
     variant. The skip-list was generalized to the underlying PATTERN
     (anything describing what was asked/classified/subjectively assessed
     about participants) rather than specific instances, in all 4.
  4. Variant A's "always prefer specific subject, avoid GaroCommunity"
     instruction was re-examined against the full 148-triple manual ground
     truth (not just page 3's 23) -- GaroPeople/GaroCommunity is the human
     team's own subject 61% of the time. The instruction was too strong and
     risked hurting accuracy outside page 3's Attire section. Refined to
     "match the sentence's own scope" instead of a blanket preference.
  5. Variant B's "check if this Subject-Object pair was already extracted"
     instruction only caught pair-level duplicates, not the TYPE-level
     inconsistency actually observed (3 different predicates for the same
     wearing-relationship across DIFFERENT subjects/objects in round 3).
     Refined to a type-level rule: one predicate name per relationship type,
     reused regardless of which specific subject/object is involved.

None of these changes reference page-3-specific vocabulary (no "attire",
"Gando/Katib/Salchak", etc as instruction targets) -- they target the
failure patterns themselves, so they should hold up on any page.

USAGE:
    python test_extraction_variants.py papers/garo_1.pdf 3 --variant baseline
    python test_extraction_variants.py papers/garo_1.pdf 3 --variant A
    python test_extraction_variants.py papers/garo_1.pdf 3 --variant B
    python test_extraction_variants.py papers/garo_1.pdf 3 --variant C
    python test_extraction_variants.py papers/garo_1.pdf 3 --variant D

Variant D (see _variant_d_prompt below) was built one turn before this
revision and already incorporates most of the same fixes independently --
it remains a separate, single "best guess" synthesis prompt, distinct from
the baseline/A/B/C isolated-variable comparison.
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

Read the passage. Identify every factual claim, relationship, practice, belief, observation, or piece of knowledge about the Garo / Mandi community discussed in the passage. This passage may come from any part of the paper -- introduction, demographics, attire, food, religion, festivals, health, household life, occupation, or any other section -- so do not assume in advance which topic it covers.

Output your answer immediately as a sequence of Cypher comment blocks. Do not include any reasoning, planning, or <think> content, and do not write anything before the first block -- your entire response must consist only of comment blocks in this exact format:

// PASSAGE: (Subject)-[PREDICATE]->(Object)
// SENTENCE REF: <exact sentence from the paper this was drawn from>
// SOURCE: <paper title placeholder>

Strict rules for the PASSAGE line:
- It MUST be written ONLY as (Subject)-[PREDICATE]->(Object). Never write a full sentence, paraphrase, or description on the PASSAGE line -- that line is a structured triple, not prose.
- Subject and Object must be short noun phrases (1-4 words) in CamelCase with no spaces, e.g. (MandiLanguage), (GaroCommunity).
- Predicate must be UPPER_CASE_WITH_UNDERSCORES ONLY -- no lowercase letters, no spaces, no mixed case. For example, write IS_USED_IN, never "IS USED IN"; write WEARS, never "WE WEAR"; write HAS_FAMILY_STRUCTURE, never "HAS_FamilyStructure". A predicate containing a space or a lowercase word is always wrong -- rewrite it before outputting the block.
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


def _variant_b_prompt(chunk_text: str) -> str:
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
- Identify the underlying relationship TYPE each fact expresses (e.g. wearing an item of clothing, practicing a belief, migrating from a place, working in an occupation) and use exactly ONE predicate name for that type everywhere it appears in this passage, regardless of which specific subject or object is involved -- e.g. if you extract (GaroMen)-[WEARS]->(Lungis), also use WEARS for (GaroWomen)-[WEARS]->(Sarees), never a different word like WEAR or WORE for the same relationship type elsewhere in this passage. Before outputting a block, check whether this relationship type already has a predicate name used earlier in this passage; if so, reuse it exactly rather than inventing a new one.
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


def _variant_c_prompt(chunk_text: str) -> str:
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
- Identify the underlying relationship TYPE each fact expresses (e.g. wearing an item of clothing, practicing a belief, migrating from a place, working in an occupation) and use exactly ONE predicate name for that type everywhere it appears in this passage, regardless of which specific subject or object is involved -- e.g. if you extract (GaroMen)-[WEARS]->(Lungis), also use WEARS for (GaroWomen)-[WEARS]->(Sarees), never a different word like WEAR or WORE for the same relationship type elsewhere in this passage. Before outputting a block, check whether this relationship type already has a predicate name used earlier in this passage; if so, reuse it exactly rather than inventing a new one.
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


def _variant_d_prompt(chunk_text: str) -> str:
    """
    PR008 / "Variant D" -- the refined prompt, built from three rounds of A/B/C
    testing on page 3 PLUS a read of the full 148-triple manual ground truth
    (KG_extraction_Garo_1.xlsx, 'Final Triples' sheet, all 7 pages / 13
    sections: Abstract, Introduction, Demographic Information, Attire, Food
    habits, Household, Health, Occupation, Religion, Festival, Land Ownership,
    Assistance/NGOs, Major Findings). Two important things came out of the
    manual sheet that changed the design vs Variant A/C:

    1. The human team's own subject choice is NOT "always most specific" --
       GaroPeople/GaroCommunity is the subject in 90/148 (61%) of the manual
       triples, including many that are clearly general community-level
       statements. Variant A's blanket "prefer specific, avoid GaroCommunity"
       instruction was measured against page 3's Attire section specifically,
       where per-gender phrasing happens to dominate -- that is NOT
       representative of the rest of the paper, and over-applying it risks
       actively hurting accuracy on other pages. This variant instructs
       matching specificity to what the SENTENCE supports, not a blanket
       preference either way -- confirmed by the human team's own notes in
       that sheet (e.g. "Keeping same node of GaroPeople, Duplication?").
    2. Every round of testing (3 rounds, all 4 prompts) hit the same two
       failure modes regardless of which variant was used: (a) study-
       methodology leakage that evolves past a literal "Respondents" keyword
       into paraphrases like "ASKED_ABOUT_X" or classification jargon, and
       (b) the known parse_ollama_blocks() bug where DeepSeek's <think>
       reasoning (or any preamble) before the first "// PASSAGE:" marker
       causes the whole response to collapse into a single UNKNOWN triple.
       Both are addressed directly and generically below -- neither fix
       assumes anything about page 3's specific content.

    Deliberately NOT included: no page-3-specific vocabulary (no "attire",
    "Gando/Katib/Salchak", or similar) is used as an instruction target --
    every named example below is pulled from a DIFFERENT section of the
    manual sheet (Festival, Household, Land Ownership, Assistance/NGOs) so
    the prompt doesn't overfit to the one page it's been tested on so far.
    """
    return f"""You are a knowledge graph extraction assistant. You will be provided with a passage from an academic research paper.

Read the passage. Identify every factual claim, relationship, practice, belief, observation, or piece of knowledge about the Garo / Mandi community discussed in the passage. This passage may come from any part of the paper -- introduction, demographics, attire, food, religion, festivals, health, household life, occupation, or any other section -- so do not assume in advance which topic it covers.

Output your answer immediately as a sequence of Cypher comment blocks. Do not include any reasoning, planning, or <think> content, and do not write anything before the first block -- your entire response must consist only of comment blocks in this exact format:

// PASSAGE: (Subject)-[PREDICATE]->(Object)
// SENTENCE REF: <exact sentence from the paper this was drawn from>
// SOURCE: <paper title placeholder>

Strict rules for the PASSAGE line:
- It MUST be written ONLY as (Subject)-[PREDICATE]->(Object). Never write a full sentence, paraphrase, or description on the PASSAGE line -- that line is a structured triple, not prose.
- Subject and Object must be short noun phrases (1-4 words) in CamelCase with no spaces, e.g. (MandiLanguage), (GaroCommunity), (WangalaFestival).
- Choose the Subject at the level of specificity the sentence itself actually supports -- neither more nor less. If the sentence names a specific subgroup, item, individual, organization, ritual, or role (e.g. GaroWomen, GaroHousehold, NGOs, MatrilinealSystem), use that specific entity as the Subject. If the sentence instead makes a general statement about the community as a whole, GaroPeople or GaroCommunity IS the correct Subject -- do not force a narrower entity onto a general statement, and do not default to a broad community-level noun when the sentence clearly names something narrower.
- Predicate must be UPPER_CASE_WITH_UNDERSCORES. Prefer a predicate already used elsewhere in this passage, or a common relationship type if one fits (e.g. IS_LOCATED_IN, LIVES_IN, MIGRATED_FROM, SPEAKS, WEARS, CELEBRATES, PRACTICES, WORKS_IN, DEPENDS_ON, BELIEVES_IN, WORSHIPS, FACES, CONSUMES) -- only invent a new predicate when none of these describe the relationship. Before outputting a block, check whether the same Subject-Object pair or fact has already been extracted under a different predicate wording in this passage; if so, do not extract it again.
- If a sentence lists multiple values for the same relationship (e.g. multiple professions, locations, languages, foods, or beliefs), output ONE SEPARATE triple per value. Never combine multiple values into a single comma-separated Object -- e.g. write (GaroCommunity)-[HAS_PROFESSION]->(Teacher) and (GaroCommunity)-[HAS_PROFESSION]->(Farmer) as two blocks, not one block with (Teacher, Farmer).
- Do not decide in advance what topics or domains to look for -- extract everything factual the passage contains about the Garo/Mandi community's culture, language, history, beliefs, practices, and lived experience, whatever section of the paper it comes from.
- Each PASSAGE line must be traceable to a specific sentence, quoted exactly in SENTENCE REF. If you cannot find an exact sentence, do not output a block for that content at all.

Skip entirely -- do not output a block for any of the following:
- Bibliographic references, author citations, journal titles, page numbers, or keyword lists.
- Anything describing the research process itself rather than the community: sample sizes, participant/respondent counts or demographics, what participants or respondents were asked, told, or observed to say, how they were classified or coded (e.g. classification schemes, occupational codes), interview or data collection methods, data analysis procedures, or any subjective assessment the researchers made about participants (e.g. calling them vulnerable, hesitant, willing, or reluctant). "Respondents" or "participants" must never appear as a Subject or Object. Only extract facts about the Garo/Mandi community itself, never facts about how the paper studied them or who was surveyed.

Output only the formatted comment blocks. No explanation, no prose, no extra text, and nothing before the first "// PASSAGE:" line.

Passage:
{chunk_text}
"""


PROMPT_VARIANTS = {
    "baseline": _baseline_prompt,
    "A": _variant_a_prompt,
    "B": _variant_b_prompt,
    "C": _variant_c_prompt,
    "D": _variant_d_prompt,
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
