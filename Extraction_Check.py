import json
import re
import argparse
from typing import List, Dict, Any

# ------------------------------------------------------------
# 1. Core Validation Functions
# ------------------------------------------------------------

CONFIDENCE_MAP = {"high": 1.0, "medium": 0.6, "low": 0.3}

def normalize_confidence(value):
    """Accepts either a High/Medium/Low label or a raw float, returns a float."""
    if isinstance(value, str):
        mapped = CONFIDENCE_MAP.get(value.strip().lower())
        if mapped is None:
            raise AssertionError(
                f"Unrecognized confidence label: '{value}'. Expected High/Medium/Low or a float 0.0-1.0."
            )
        return mapped
    return value

def validate_json_structure(output_text: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(output_text)
    except json.JSONDecodeError:
        raise AssertionError(f"Output is not valid JSON. Got: {output_text[:200]}...")
    
    if isinstance(data, list):
        triples = data
    elif isinstance(data, dict) and "triples" in data:
        triples = data["triples"]
        assert isinstance(triples, list), "'triples' is not a list."
    else:
        raise AssertionError("JSON must be a list of triples or an object with a 'triples' key.")
    
    return triples

def validate_triple_format(triple: Dict[str, Any], strict_predicate: bool = False) -> None:
    required_keys = {"subject", "predicate", "object", "confidence"}
    evidence_key = None
    if "evidence" in triple and triple["evidence"]:
        evidence_key = "evidence"
    elif "source_section" in triple and triple["source_section"]:
        evidence_key = "source_section"
    else:
        raise AssertionError("Missing evidence field (expected 'evidence' or 'source_section').")
    
    missing = required_keys - set(triple.keys())
    if missing:
        raise AssertionError(f"Missing keys: {missing}")
    
    # Reject placeholder triples from failed extraction parsing (e.g. DeepSeek
    # output that didn't match the expected (Subject)-[PREDICATE]->(Object)
    # format, which parse_ollama_blocks() falls back to labeling UNKNOWN).
    if triple["subject"].strip().upper() == "UNKNOWN" or triple["object"].strip().upper() == "UNKNOWN":
        raise AssertionError("Triple contains UNKNOWN placeholder — extraction failed to parse a real subject/object.")

    # Reject triples whose sentence-level evidence is the model literally
    # echoing the prompt's own template placeholder text back, instead of
    # filling in a real quoted sentence -- found on a garo_1 page-3 re-run
    # where roughly half the triples had sentence_ref == "<exact sentence
    # from the paper this was drawn from>" (the prompt's own SENTENCE REF
    # placeholder, copied verbatim) or a similar self-referential non-quote
    # like "the passage provided". The prompt explicitly instructs the
    # model to skip a triple rather than output one it can't ground in a
    # real sentence -- this is that rule not being followed. Deliberately
    # checking "sentence_ref" and "passage" directly here rather than the
    # evidence_key resolved above: evidence_key resolves to "source_section"
    # for every triple in this pipeline (no triple has ever populated
    # "evidence" -- see subject_specificity.py's get_evidence_sentence()),
    # and source_section is just "Page N", so it would never contain this
    # text and this check would silently catch nothing. Unlike
    # subject-collapse or artifact filtering, there's no judgment call
    # here: template text can never be genuine evidence, so this is a hard
    # reject, not a filter.
    PLACEHOLDER_EVIDENCE_PHRASES = [
        "exact sentence from the paper this was drawn from",
        "the passage provided",
        "paper title placeholder",
        "sentence from the paper this was drawn from",
    ]
    sentence_level_text = f"{triple.get('sentence_ref', '')} {triple.get('passage', '')}".strip().lower()
    for phrase in PLACEHOLDER_EVIDENCE_PHRASES:
        if phrase in sentence_level_text:
            raise AssertionError(
                f"Evidence field echoes the prompt's own template placeholder "
                f"('{phrase}') instead of a real quoted sentence — extraction "
                f"failed to ground this triple in the source text."
            )

    # Predicate format
    if strict_predicate:
        pattern = r'^[A-Z][A-Z0-9_]+$'          # UPPER_SNAKE with optional digits
    else:
        pattern = r'^[A-Z][A-Za-z0-9_/ \-]+$'   # relaxed: letters, digits, spaces, /, -
    
    if not re.match(pattern, triple["predicate"]):
        raise AssertionError(
            f"Predicate '{triple['predicate']}' does not match required pattern. "
            f"(strict={strict_predicate})"
        )
    
    confidence_value = normalize_confidence(triple["confidence"])
    assert 0.0 <= confidence_value <= 1.0, f"Confidence {confidence_value} out of range."
    assert isinstance(triple["subject"], str) and triple["subject"].strip(), "Subject is empty."
    assert isinstance(triple["object"], str) and triple["object"].strip(), "Object is empty."
    assert isinstance(triple[evidence_key], str) and triple[evidence_key].strip(), f"{evidence_key} is empty."

# ------------------------------------------------------------
# 2. Artifact Filtering Tests (generic)
# ------------------------------------------------------------

ARTIFACT_KEYWORDS = [
    "participant", "interview", "snowball", "consent", "pseudonym",
    "audio-recorded", "transcribed", "coded", "questionnaire",
    "researcher", "researchers", "we analyzed", "we conducted",
    "sample size", "n=", "n =", "age range", "male", "female",
    "semi-structured", "thematic analysis", "data collection",
    "key words", "keywords",
    # Added 2026-09-09 after reviewing the garo_1.pdf full-paper run: 27
    # methodology/research-process triples reached Neo4j despite this
    # filter, none matched by the list above. Checked against all 325
    # triples that run produced -- no false positives in this paper's
    # vocabulary (see the predicate-only list below for the ones that
    # DID need scoping to avoid a false positive).
    "respondent",        # catches "Respondents" as Subject/Object (singular or plural)
    "demographic",       # catches "DemographicInformation" node and "HAS_DEMOGRAPHICBACKGROUND"
    "historicaldata",    # catches USED_HISTORICALDATA (the study's own data sources)
    "historical data",
    "purposive sampling",
    # Added 2026-09-09, broader research-methodology vocabulary not yet
    # observed as a leak in this paper but common in academic papers
    # generally -- each checked against all 326 triples from the
    # garo_1.pdf run with zero false-positive hits before being added
    # (one, "case study", DOES hit -- but it's one of the 27 already-
    # known leaks, already caught via the predicate marker below, so
    # this is redundant-but-harmless defense-in-depth for a future paper
    # that phrases the same leak under a different predicate name).
    "case study", "focus group", "field notes", "fieldnotes",
    "informed consent", "ethical approval", "ethics committee", "irb",
    "inclusion criteria", "exclusion criteria",
    "convenience sampling", "random sampling", "snowball sampling",
    "literature review", "research design", "study design",
    "data saturation", "member checking", "triangulation",
    "content analysis", "grounded theory", "inter-rater",
    "the present study", "the current study", "this study", "this paper",
    "this article", "our study", "the study", "et al", "doi:", "issn",
    "limitations of the study", "further research", "future research",
    "future studies", "self-reported", "self reported", "recruited",
    "recruitment",
]

# Predicate-only substring markers. These words are legitimate inside a
# Subject or Object -- e.g. "EstablishInstitutionAndResearchCenter" is a
# real community recommendation from garo_1.pdf, not a leak, and
# "(GaroCommunity)-[HAS_PROBLEM]->(Poor Settlement Surveys)" is a real
# land-ownership finding that would false-positive on a whole-triple
# "survey" keyword -- but a PREDICATE describes a relationship TYPE, not
# an entity, so none of these have any legitimate reason to appear inside
# one in this schema. Kept separate from ARTIFACT_KEYWORDS (which scans
# the whole triple) specifically to avoid false-flagging triples like
# those two.
RESEARCH_PROCESS_PREDICATE_MARKERS = [
    "research", "methodology", "method", "objective", "sample", "aim",
    # Added 2026-09-09, same rationale as above -- zero collisions
    # against current predicates, added proactively for future papers:
    "survey", "study", "design", "criteria", "analysis", "framework",
    "hypothesis", "literature", "limitation",
]

def flag_artifact_triples(triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flagged = []
    for idx, triple in enumerate(triples):
        evidence_text = triple.get("evidence", "") + triple.get("source_section", "")
        text_to_scan = f"{triple['subject']} {triple['predicate']} {triple['object']} {evidence_text}".lower()
        predicate_text = triple.get("predicate", "").lower()

        matched_keyword = None
        for keyword in ARTIFACT_KEYWORDS:
            if keyword in text_to_scan:
                matched_keyword = keyword
                break

        if matched_keyword is None:
            for marker in RESEARCH_PROCESS_PREDICATE_MARKERS:
                if marker in predicate_text:
                    matched_keyword = f"predicate:{marker}"
                    break

        if matched_keyword:
            flagged.append({
                "index": idx,
                "triple": triple,
                "matched_keyword": matched_keyword
            })
    return flagged

# ------------------------------------------------------------
# 3. Main Test Runner
# ------------------------------------------------------------

def run_all_tests(llm_output_string: str, strict_predicate: bool = False) -> bool:
    print("Running Validation Suite...")
    print(f"  Predicate mode: {'strict (UPPER_SNAKE)' if strict_predicate else 'relaxed (letters, digits, spaces, /, -)'}")
    
    # Test 1 & 2: Structure and format
    try:
        triples = validate_json_structure(llm_output_string)
        for t in triples:
            validate_triple_format(t, strict_predicate)
        print("✅ [PASS] JSON structure and triple format are valid.")
    except AssertionError as e:
        print(f"❌ [FAIL] Format validation: {e}")
        return False
    
    # Test 3: Artifact flagging (warning, not a failure)
    flagged = flag_artifact_triples(triples)
    if flagged:
        print(f"[WARN] Found {len(flagged)} triples that may contain research artifacts:")
        for item in flagged:
            print(f"  - Index {item['index']}: Contains '{item['matched_keyword']}'")
            print(f"    Triple: ({item['triple']['subject']})-[{item['triple']['predicate']}]->({item['triple']['object']})")
    else:
        print("✅ [PASS] No obvious artifact keywords detected.")
    
    # Summary
    print(f"\nSummary: {len(triples)} triples extracted.")
    print("Structural validation passed. Review artifact warnings if any.")
    return True

# ------------------------------------------------------------
# 4. Command‑line entry point
# ------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Broad validation of KG extraction from a JSON file."
    )
    parser.add_argument("json_file", help="Path to the JSON file to test.")
    parser.add_argument("--strict", action="store_true",
                        help="Enforce UPPER_SNAKE_CASE for predicates (no spaces, slashes, hyphens, or lower-case).")
    args = parser.parse_args()
    
    try:
        with open(args.json_file, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"Testing file: {args.json_file}")
        print(f"File contents preview: {content[:200]}...\n")
        run_all_tests(content, strict_predicate=args.strict)
    except FileNotFoundError:
        print(f"Error: File '{args.json_file}' not found.")
    except Exception as e:
        print(f"Error reading file: {e}")