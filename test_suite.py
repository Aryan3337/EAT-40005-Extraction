#!/usr/bin/env python3
"""
Test Suite for the Knowledge Repository

Tanjila requested this after the Sprint 4 demo: a structured test suite to
validate what's actually in the knowledge repository before further chatbot
work continues, given that a ~600 fact count from only 2-3 papers looked
implausible to her.

This runs against the REAL retrieval layer in rag.py, the same
code path the chatbot uses. Four test categories:

  certain      - questions about facts we KNOW are in the KG (based on
                 real triples from paper1_kg_extractions.csv). Should match,
                 and the specific expected entity should show up in the result.
  ambiguous    - plausibly related questions with no fixed expected outcome;
                 recorded for review, not pass/failed.
  out_of_bound - questions with nothing to do with any processed paper.
                 Should trigger the "I don't have information on that."
                 fallback and get logged as a knowledge gap.
  regression   - added after the first run of this suite surfaced two real
                 defects (see notes below). Each case pins down the CURRENT,
                 observed behaviour of a specific known issue so that if it's
                 ever fixed (or regresses further), this suite tells us
                 immediately rather than silently drifting. A "pass" here
                 means the system is behaving the way we last confirmed it
                 behaves -- not necessarily the way we'd like it to behave.

Background on the two known issues tracked under "regression":
  1. Bare/generic entities (e.g. "19", "3", "6" pulled straight out of a
     participant-count sentence) can cause false-positive matches on totally
     unrelated questions that merely happen to contain that digit somewhere
     -- this is what caused the original O-004 failure ("How old was I in
     2019?" matched on "19").
  2. Near-duplicate entity strings (e.g. "GaroCommunity" vs "Garo Community")
     inflate the apparent size of the repository without adding real
     information, since exact-string entity indexing treats them as two
     unrelated entities.

Usage:
    python test_suite.py --kg paper1_kg_extractions.csv
    python test_suite.py --kg paper1_kg_extractions.csv --approach cypher
    python test_suite.py --kg paper1_kg_extractions.csv --out-dir results/

Outputs (into test_suite_results/ by default):
    run_<timestamp>.json   - full structured results
    run_<timestamp>.csv    - same results, spreadsheet friendly
"""

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from rag import RAGSkeleton, KnowledgeGraph, NO_MATCH_MESSAGE

RESULTS_DIR = Path("test_suite_results")

# Predicates that double as common English words are a structural risk
# factor for the low-confidence predicate fallback in ConceptRetriever: any
# question containing that everyday word -- regardless of topic -- can
# spuriously "match". Used by the repository audit below, and referenced by
# several ambiguous/regression cases.
COMMON_WORD_PREDICATES_TO_WATCH = {
    "is", "are", "was", "were", "has", "have", "had", "use", "uses", "used",
    "can", "need", "want", "know", "live", "lives", "speak", "speaks",
    "follow", "follows", "practice",
}


# ============================================================
# 1. Test cases
# ============================================================

TEST_CASES = [
    # ------------------------------------------------------------------
    # CERTAIN
    # Real triples pulled directly from paper1_kg_extractions.csv. All of
    # these use single-word subjects/objects on purpose (see the regression
    # notes / repository audit further down for why compound, multi-word
    # entity names like "GaroCommunity" don't reliably match a naturally
    # phrased question).
    # ------------------------------------------------------------------
    {
        "id": "C-001",
        "category": "certain",
        "question": "Is the Garo community located in Bangladesh?",
        "source_paper": "paper1",
        "expect_entities": ["bangladesh"],
        "notes": "Based on: (GaroCommunity)-[EXIST_IN]->(Bangladesh), Page 2.",
    },
    {
        "id": "C-002",
        "category": "certain",
        "question": "Do Garo people live in Modhupur?",
        "source_paper": "paper1",
        "expect_entities": ["modhupur"],
        "notes": "Based on: (GaroLocation)-[LIVES_IN]->(Modhupur), Page 3.",
    },
    {
        "id": "C-003",
        "category": "certain",
        "question": "What is Chibok?",
        "source_paper": "paper1",
        "expect_entities": ["chibok"],
        "notes": "Based on: (GaroDialect)-[IS_KNOWN_AS]->(Chibok), Page 3.",
    },
    {
        "id": "C-004",
        "category": "certain",
        "question": "Does Christianity relate to Garo religion?",
        "source_paper": "paper1",
        "expect_entities": ["christianity"],
        "notes": "Based on: (GaroReligion)-[IS_PRACTICED_BY]->(Christianity), Page 3.",
    },
    {
        "id": "C-005",
        "category": "certain",
        "question": "Are the Garo also known as Garoini?",
        "source_paper": "paper1",
        "expect_entities": ["garoini"],
        "notes": "Based on: (Garo)-[ARE_KNOWN_AS]->(Garoini), Page 3.",
    },
    {
        "id": "C-006",
        "category": "certain",
        "question": "Do Garo people live in Netrokona?",
        "source_paper": "paper1",
        "expect_entities": ["netrokona"],
        "notes": "Based on: (GaroLocation)-[LIVES_IN]->(Netrokona), Page 3.",
    },
    {
        "id": "C-007",
        "category": "certain",
        "question": "Do Garo people live in Tangail?",
        "source_paper": "paper1",
        "expect_entities": ["tangail"],
        "notes": "Based on: (GaroLocation)-[LIVES_IN]->(Tangail), Page 3.",
    },
    {
        "id": "C-008",
        "category": "certain",
        "question": "Does anyone from this study work in Russia?",
        "source_paper": "paper1",
        "expect_entities": ["russia"],
        "notes": "Based on: (M1)-[WORKS_AT]->(Russia), Page 12.",
    },
    {
        "id": "C-009",
        "category": "certain",
        "question": "Does UNESCO celebrate mother languages?",
        "source_paper": "paper1",
        "expect_entities": ["unesco"],
        "notes": "Based on: (UNESCO)-[CELEBRATES]->(PowerOfMotherLanguages), Page 20.",
    },
    {
        "id": "C-010",
        "category": "certain",
        "question": "Do Garo women use turmeric in beauty rituals?",
        "source_paper": "paper1",
        "expect_entities": ["turmeric"],
        "notes": "Based on: (GaroWomen)-[USE_TURMERIC]->(Turmeric), Page 21.",
    },
    {
        "id": "C-011",
        "category": "certain",
        "question": "Do Mandi women use indigo?",
        "source_paper": "paper1",
        "expect_entities": ["indigo"],
        "notes": "Based on: (MandiWomen)-[USE_INDIGO]->(Indigo), Page 21.",
    },
    {
        "id": "C-012",
        "category": "certain",
        "question": "Do Garo women use ashes in beauty rituals?",
        "source_paper": "paper1",
        "expect_entities": ["ashes"],
        "notes": "Based on: (GaroWomen)-[USE_ASHES]->(Ashes), Page 21.",
    },
    {
        "id": "C-013",
        "category": "certain",
        "question": "Do Mandi women use clay in beauty rituals?",
        "source_paper": "paper1",
        "expect_entities": ["clay"],
        "notes": "Based on: (MandiWomen)-[USE_CLAY]->(Clay), Page 21.",
    },
    {
        "id": "C-014",
        "category": "certain",
        "question": "Are there approximately 135000 speakers of the Garo language?",
        "source_paper": "paper1",
        "expect_entities": ["135000"],
        "notes": "Based on: (GaroLanguage)-[HAS_NUMBER_OF_SPEAKERS]->(135000), Page 16. "
                 "Only matches because the question repeats the exact digit "
                 "string -- see the short/generic entity risk noted for "
                 "REG-001..003 below.",
    },
    {
        "id": "C-015",
        "category": "certain",
        "question": "Do Garo people call themselves Mandi?",
        "source_paper": "paper1",
        "expect_entities": ["mandi"],
        "notes": "Based on: (GaroSelfName)-[IS_CALLED]->(Mandi), Page 3.",
    },

    # ------------------------------------------------------------------
    # AMBIGUOUS
    # No fixed pass/fail bar -- these exist to see how the matcher behaves
    # at the edges, and to flag when a "match" is a weak, low-confidence
    # match rather than a genuine hit.
    # ------------------------------------------------------------------
    {
        "id": "A-001",
        "category": "ambiguous",
        "question": "What language do the Mandi people speak at home?",
        "source_paper": "paper1",
        "expect_entities": [],
        "notes": "Real topic but phrased with spaces, so entity substring "
                 "match likely misses compound entities entirely.",
    },
    {
        "id": "A-002",
        "category": "ambiguous",
        "question": "Tell me about religious practices in the Garo community",
        "source_paper": "paper1",
        "expect_entities": [],
        "notes": "The word 'practices' contains predicate 'practice', so this is "
                 "likely to hit the low-confidence predicate fallback rather "
                 "than a real entity match -- worth checking is_gap here.",
    },
    {
        "id": "A-003",
        "category": "ambiguous",
        "question": "How is the Mandi language maintained across generations?",
        "source_paper": "paper1",
        "expect_entities": [],
        "notes": "Real topic in the paper but phrased generically.",
    },
    {
        "id": "A-004",
        "category": "ambiguous",
        "question": "What do Garo people do at church on Sundays?",
        "source_paper": "paper1",
        "expect_entities": [],
        "notes": "'church' and 'sunday' are both real single-word entities in "
                 "the KG (Church, Sunday, EverySunday) so this could go "
                 "either way depending on which gets picked up.",
    },
    {
        "id": "A-005",
        "category": "ambiguous",
        "question": "How many dialects does the Garo language have?",
        "source_paper": "paper1",
        "expect_entities": [],
        "notes": "The KG stores the dialect count as the entity 'Eight', a "
                 "common English word -- worth checking whether it "
                 "accidentally fires here or stays silent.",
    },
    {
        "id": "A-006",
        "category": "ambiguous",
        "question": "What professions do Garo men have?",
        "source_paper": "paper1",
        "expect_entities": [],
        "notes": "The professions are stored as one long compound entity "
                 "string per row, so natural phrasing is unlikely to match "
                 "even though the topic is directly covered.",
    },
    {
        "id": "A-007",
        "category": "ambiguous",
        "question": "Tell me about beauty rituals among Mandi women",
        "source_paper": "paper1",
        "expect_entities": [],
        "notes": "'MandiWomen' is compound and won't match, but individual "
                 "single-word objects (Indigo, Clay) might surface anyway "
                 "if they were already returned via another entity.",
    },
    {
        "id": "A-008",
        "category": "ambiguous",
        "question": "Do older Garo generations still try to preserve their language?",
        "source_paper": "paper1",
        "expect_entities": [],
        "notes": "Real topic (OlderGenerationsGaroCommunity / KEEP_TRYING) but "
                 "the entity is compound and heavily paraphrased here.",
    },

    # ------------------------------------------------------------------
    # OUT-OF-BOUND
    # Should trigger the fallback and get logged. Includes a few
    # deliberately awkward inputs (empty string, gibberish, pure digits) on
    # top of the original four, since those are exactly the kind of input a
    # real user eventually sends.
    # ------------------------------------------------------------------
    {
        "id": "O-001",
        "category": "out_of_bound",
        "question": "What suburb is Swinburne located?",
        "source_paper": None,
        "expect_entities": [],
        "notes": "",
    },
    {
        "id": "O-002",
        "category": "out_of_bound",
        "question": "How do I come up with this test suite?",
        "source_paper": None,
        "expect_entities": [],
        "notes": "",
    },
    {
        "id": "O-003",
        "category": "out_of_bound",
        "question": "What's today's weather going to be?",
        "source_paper": None,
        "expect_entities": [],
        "notes": "",
    },
    {
        "id": "O-004",
        "category": "out_of_bound",
        "question": "How old was I in 2019?",
        "source_paper": None,
        "expect_entities": [],
        "notes": "Known false positive -- the KG contains a bare entity '19', "
                 "which matches inside '2019'. See REG-001 for a cleaner, "
                 "dedicated reproduction of this same underlying defect.",
    },
    {
        "id": "O-005",
        "category": "out_of_bound",
        "question": "What's the best pizza topping combination?",
        "source_paper": None,
        "expect_entities": [],
        "notes": "",
    },
    {
        "id": "O-006",
        "category": "out_of_bound",
        "question": "Can you help me debug this JavaScript error?",
        "source_paper": None,
        "expect_entities": [],
        "notes": "",
    },
    {
        "id": "O-007",
        "category": "out_of_bound",
        "question": "Who won the World Cup in 2022?",
        "source_paper": None,
        "expect_entities": [],
        "notes": "Deliberately similar shape to O-004 ('...in <year>') to check "
                 "whether a different bare year triggers the same bug; the "
                 "KG has no standalone '2022' or '22' entity so this one "
                 "should pass.",
    },
    {
        "id": "O-008",
        "category": "out_of_bound",
        "question": "asdkjfh qwoeiru zxcvb",
        "source_paper": None,
        "expect_entities": [],
        "notes": "Gibberish input -- should never match anything.",
    },
    {
        "id": "O-009",
        "category": "out_of_bound",
        "question": "",
        "source_paper": None,
        "expect_entities": [],
        "notes": "Empty string edge case.",
    },
    {
        "id": "O-010",
        "category": "out_of_bound",
        "question": "     ",
        "source_paper": None,
        "expect_entities": [],
        "notes": "Whitespace-only edge case.",
    },
    {
        "id": "O-011",
        "category": "out_of_bound",
        "question": "1234567890",
        "source_paper": None,
        "expect_entities": [],
        "notes": "Pure digit string -- expected to reproduce the same bare-"
                 "entity bug as O-004, since it contains '3' and '6' as "
                 "substrings, both of which are entities in this KG.",
    },
    {
        "id": "O-012",
        "category": "out_of_bound",
        "question": "What is 2 + 2?",
        "source_paper": None,
        "expect_entities": [],
        "notes": "Control case: contains a digit, but not one of the specific "
                 "bare-digit entities in this KG, so this should pass "
                 "cleanly and shows the bug is about specific overlaps, "
                 "not numbers in general.",
    },

    # ------------------------------------------------------------------
    # REGRESSION
    # Pins down the CURRENT behaviour of known issues so we notice if it
    # changes. See the module docstring for background on both issues.
    # A "passed: True" here means "behaves the way we last confirmed",
    # which for REG-001..003 unfortunately means "still has the bug".
    # ------------------------------------------------------------------
    {
        "id": "REG-001",
        "category": "regression",
        "question": "I turned 19 last year, is that a big deal?",
        "source_paper": None,
        "expect_entities": [],
        "notes": "Reproduces the bare-entity '19' false positive from O-004 "
                 "with cleaner phrasing (no other risk factors in the "
                 "sentence). Confirmed present as of this run; see "
                 "(GaroCommunity)-[HAS_NUMBER_OF_PARTICIPANTS]->(19), Page 21.",
    },
    {
        "id": "REG-002",
        "category": "regression",
        "question": "I have 3 cats, is that too many?",
        "source_paper": None,
        "expect_entities": [],
        "notes": "Same bug, different bare-digit entity. See "
                 "(GaroCommunity)-[HAS_NUMBER_OF_MALE_PARTICIPANTS]->(3), Page 21.",
    },
    {
        "id": "REG-003",
        "category": "regression",
        "question": "Could you give me 6 examples of good passwords?",
        "source_paper": None,
        "expect_entities": [],
        "notes": "Same bug, different bare-digit entity. See "
                 "(GaroCommunity)-[HAS_NUMBER_OF_FEMALE_PARTICIPANTS]->(6), Page 21.",
    },
    {
        "id": "REG-004",
        "category": "regression",
        "question": "Do Garo people live in Modhupur?",
        "source_paper": "paper1",
        "expect_entities": ["modhupur"],
        "notes": "Guards against the earlier 'confidence tracking' bug where a "
                 "genuine entity match got mis-flagged as a knowledge gap. "
                 "Deliberately run immediately after an out-of-bound query "
                 "on the SAME skeleton instance (see run_suite) to also "
                 "catch any state leaking between calls.",
    },
]


# ============================================================
# 2. Runner
# ============================================================

def evaluate_case(skeleton: RAGSkeleton, case: dict, top_k: int) -> dict:
    """Run one test case through the real retrieval + fallback pipeline and
    record what actually happened."""
    # skeleton.answer() runs the full production path (retrieval, gap
    # detection, gap logging). We call it once so logging behavior matches
    # exactly what a real user query would do.
    response, is_gap = skeleton.answer(case["question"], top_k=top_k)

    # skeleton.query() alone (no side effects) to inspect the raw triples
    # for entity verification below.
    triples = skeleton.query(case["question"], top_k=top_k)

    matched_entities = set()
    for t in triples:
        matched_entities.add(t.get("subject", "").lower())
        matched_entities.add(t.get("object", "").lower())

    expect_entities = [e.lower() for e in case.get("expect_entities", [])]
    entities_found = [e for e in expect_entities if any(e in me for me in matched_entities)]
    entities_missing = [e for e in expect_entities if e not in entities_found]

    category = case["category"]
    if category == "certain":
        passed = (not is_gap) and not entities_missing and bool(expect_entities)
    elif category == "out_of_bound":
        passed = is_gap and response == NO_MATCH_MESSAGE
    elif category == "regression":
        # Regression cases pin down PREVIOUSLY OBSERVED behaviour, which is
        # not always "correct" behaviour. REG-001..003 pass when the known
        # bug still reproduces (is_gap is False -- i.e. it incorrectly
        # "matched" something); REG-004 pass when a genuine match is
        # correctly recognised and NOT flagged as a gap.
        if case["id"] in ("REG-001", "REG-002", "REG-003"):
            passed = not is_gap
        else:
            passed = (not is_gap) and not entities_missing and bool(expect_entities)
    else:  # ambiguous — informational only
        passed = None

    return {
        "id": case["id"],
        "category": category,
        "question": case["question"],
        "source_paper": case.get("source_paper"),
        "is_gap": is_gap,
        "num_triples_returned": len(triples),
        "expected_entities": case.get("expect_entities", []),
        "entities_found": entities_found,
        "entities_missing": entities_missing,
        "response_preview": response[:150],
        "passed": passed,
        "notes": case.get("notes", ""),
    }


def run_suite(kg_path: str, approach: str, top_k: int):
    skeleton = RAGSkeleton(kg_path, approach=approach)
    results = []
    for case in TEST_CASES:
        # REG-004 depends on running right after an out-of-bound query on
        # the same skeleton instance, to check for state leaking between
        # back-to-back calls (the class of bug that caused the earlier
        # confidence-tracking issue). We piggyback on whatever out-of-bound
        # case already ran immediately before it in TEST_CASES order rather
        # than firing an extra throwaway query, so the suite still reflects
        # one query per listed case.
        results.append(evaluate_case(skeleton, case, top_k))
    return results, skeleton.kg


# ============================================================
# 3. Repository audit
# ============================================================

def audit_repository(kg: KnowledgeGraph) -> dict:
    total_triples = len(kg.triples)
    total_entities = len(kg.get_all_entities())

    papers = Counter(t.get("paper", "Unknown") for t in kg.triples)

    # Flag entity names that normalize to the same thing (case/space/
    # underscore-insensitive) but are stored as separate strings — a likely
    # source of inflated fact counts, since exact-string matching means
    # "Garo Women" / "GaroWomen" would count as two different entities.
    def normalize(n):
        return "".join(ch for ch in n.lower() if ch.isalnum())

    buckets = {}
    for e in kg.get_all_entities():
        key = normalize(e)
        buckets.setdefault(key, []).append(e)
    duplicate_groups = {k: v for k, v in buckets.items() if len(v) > 1}

    # Flag entities that are short and/or purely numeric. These are a
    # structural risk factor for false-positive matches (see REG-001..003):
    # a bare "19" or "3" can match inside almost any question that happens
    # to contain that digit, regardless of topic.
    short_generic_entities = sorted(
        e for e in kg.get_all_entities()
        if len(e) <= 2 or e.isdigit()
    )

    # Flag predicates that double as common English words. These make the
    # ConceptRetriever's low-confidence fallback (see rag.py, SCRUM-173)
    # more likely to fire on totally unrelated questions.
    risky_predicates = sorted(
        p for p in set(t["predicate"].lower() for t in kg.triples)
        if p in COMMON_WORD_PREDICATES_TO_WATCH
    )

    return {
        "total_triples": total_triples,
        "total_entities": total_entities,
        "triples_per_paper": dict(papers),
        "duplicate_entity_groups": duplicate_groups,
        "short_generic_entities": short_generic_entities,
        "risky_predicates": risky_predicates,
    }


# ============================================================
# 4. CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Knowledge repository test suite (SCRUM-194..198)")
    parser.add_argument("--kg", required=True, help="Path to KG CSV file (e.g. paper1_kg_extractions.csv)")
    parser.add_argument("--approach", choices=["concept", "cypher"], default="concept",
                        help="Retrieval approach to test (default: concept)")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out-dir", default=str(RESULTS_DIR), help="Where to write results/report")
    args = parser.parse_args()

    if not Path(args.kg).exists():
        print(f"File not found: {args.kg}")
        sys.exit(1)

    print("=" * 70)
    print("KNOWLEDGE REPOSITORY TEST SUITE")
    print("=" * 70)

    results, kg = run_suite(args.kg, args.approach, args.top_k)
    audit = audit_repository(kg)

    by_cat = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)

    print(f"\nRepository: {audit['total_triples']} triples, {audit['total_entities']} entities\n")
    for cat in ("certain", "ambiguous", "out_of_bound", "regression"):
        cases = by_cat.get(cat, [])
        if not cases:
            continue
        if cat == "ambiguous":
            gap_count = sum(1 for c in cases if c["is_gap"])
            print(f"  {cat}: {gap_count}/{len(cases)} fell back to no-info (informational)")
        else:
            passed = sum(1 for c in cases if c["passed"])
            print(f"  {cat}: {passed}/{len(cases)} passed")

    print(f"\n  duplicate entity groups found: {len(audit['duplicate_entity_groups'])}")
    print(f"  short/generic entities found: {len(audit['short_generic_entities'])} "
          f"({', '.join(audit['short_generic_entities']) or 'none'})")
    print(f"  predicates overlapping common words: {len(audit['risky_predicates'])} "
          f"({', '.join(audit['risky_predicates']) or 'none'})")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    json_path = out_dir / f"run_{timestamp}.json"
    csv_path = out_dir / f"run_{timestamp}.csv"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"results": results, "audit": audit}, f, indent=2, ensure_ascii=False)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["id", "category", "question", "source_paper", "is_gap",
                      "num_triples_returned", "expected_entities", "entities_found",
                      "entities_missing", "response_preview", "passed", "notes"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = dict(r)
            for k in ("expected_entities", "entities_found", "entities_missing"):
                row[k] = "; ".join(row[k])
            writer.writerow(row)

    print(f"\nResults saved:\n  {json_path}\n  {csv_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()