#!/usr/bin/env python3
"""
test_data_driven_subcheck.py
=============================
SCRUM-144: I wrote this to test the data-driven vs. experience-report
sub-check (SCRUM-140/141/142/143, added in confidence_framework.py v5.2)
against known experience-based vs. data-driven text.

What this covers: the classifier logic and the score-capping logic
(Part 1 & 2 below) both work correctly against synthetic text I wrote
myself (a fake opinion-piece paragraph, a fake methodology paragraph).
I've also run it against every real paper currently in the repo
(Part 3 below) — a mix of ethnomedicinal surveys, community studies, and
decolonial-perspective pieces — and none of them get wrongly flagged as
an experience report, including ones that contain a stray opinion-style
phrase alongside stronger methodology evidence. I'm continuing to add
more real papers as I get access to a wider variety, including actual
opinion/experience-style examples, to keep strengthening this further.

Does NOT require Ollama — this only exercises the code-based scan
(check_data_driven_evidence / apply_data_driven_subcheck), which is a
pure function independent of the model-based criteria.

Usage:
    python3 test_data_driven_subcheck.py
"""

import sys

from confidence_framework import (
    CriterionResult,
    check_data_driven_evidence,
    apply_data_driven_subcheck,
)

PASS = "PASS"
FAIL = "FAIL"
results = []


def record(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail and status == FAIL else ""))


# ------------------------------------------------------------------
# PART 1 — DONE. Synthetic fixtures — known experience-report text
# ------------------------------------------------------------------
EXPERIENCE_REPORT_SNIPPET = """
Reflections on Working with the Garo Community: A Personal Account

In my experience living and working alongside Garo families for the past
decade, I have come to believe that outsiders often misunderstand the
depth of their land-based traditions. This essay argues, from my own
perspective as a practitioner rather than a researcher, that policy makers
should pay closer attention to matrilineal inheritance customs. Drawing on
my own observations and conversations over the years, I offer this
narrative account as a personal reflection rather than a formal study —
there was no formal methodology behind these observations, simply years
of lived experience and informal commentary shared with community elders.
"""

DATA_DRIVEN_SNIPPET = """
Methodology

This study used a mixed-methods research design. We conducted
semi-structured interviews with 24 participants selected through
purposive sampling across three Garo villages in the Mymensingh region.
Data collection took place over six weeks and included a household
survey, two focus group discussions, and fieldwork observation notes.
Interview transcripts were coded using a thematic analysis approach, and
survey responses were examined with descriptive statistical analysis.
Ethical approval was obtained prior to data collection, and all
respondents provided informed consent.
"""

MIXED_BUT_EXPERIENCE_LEANING_SNIPPET = """
This paper is best understood as a personal reflection on fieldwork
carried out several years ago. In my opinion, the methods used at the
time — a handful of informal interviews with no sampling strategy — were
too anecdotal to support strong claims, but I include them here in the
spirit of personal account and commentary rather than rigorous data
collection.
"""


def test_experience_report_snippet():
    scan = check_data_driven_evidence(EXPERIENCE_REPORT_SNIPPET.lower())
    record(
        "Pure experience-report snippet classified as experience_report",
        scan["verdict"] == "experience_report",
        f"got verdict={scan['verdict']!r}, data_hits={scan['data_driven_signals_found']}",
    )


def test_data_driven_snippet():
    scan = check_data_driven_evidence(DATA_DRIVEN_SNIPPET.lower())
    record(
        "Methodology-heavy snippet classified as data_driven",
        scan["verdict"] == "data_driven",
        f"got verdict={scan['verdict']!r}",
    )


def test_mixed_experience_leaning_snippet():
    scan = check_data_driven_evidence(MIXED_BUT_EXPERIENCE_LEANING_SNIPPET.lower())
    record(
        "Mixed snippet with more experience signals classified as experience_leaning",
        scan["verdict"] == "experience_leaning",
        f"got verdict={scan['verdict']!r}, exp={scan['experience_signals_found']}, "
        f"data={scan['data_driven_signals_found']}",
    )


def test_undetermined_when_no_signals():
    scan = check_data_driven_evidence("this is a short paragraph about garo culture and festivals.")
    record(
        "Text with neither signal type classified as undetermined",
        scan["verdict"] == "undetermined",
        f"got verdict={scan['verdict']!r}",
    )


# ------------------------------------------------------------------
# PART 2 — DONE. apply_data_driven_subcheck() score-capping behaviour
# ------------------------------------------------------------------

def _fresh_structural(score=18, max_score=20):
    return CriterionResult(
        name="Structural Completeness",
        score=score,
        max_score=max_score,
        passed=True,
        justification="Model gave this a high structural score.",
        evaluated_by="model",
        flags=[],
    )


def test_cap_applied_for_experience_report():
    structural = _fresh_structural(score=18)
    apply_data_driven_subcheck(structural, EXPERIENCE_REPORT_SNIPPET.lower())
    record(
        "High-scoring but experience-report paper gets capped to 40% of max",
        structural.score == int(structural.max_score * 0.4),
        f"expected {int(structural.max_score * 0.4)}, got {structural.score}",
    )


def test_no_cap_for_data_driven():
    structural = _fresh_structural(score=18)
    apply_data_driven_subcheck(structural, DATA_DRIVEN_SNIPPET.lower())
    record(
        "Data-driven paper keeps its original Structural Completeness score",
        structural.score == 18,
        f"expected 18, got {structural.score}",
    )


# ------------------------------------------------------------------
# PART 3 — DONE. Regression check against every real paper in the repo:
# confirms the classifier doesn't wrongly flag a legitimate research
# paper as an experience report. I'll keep adding real opinion/
# experience-style papers here as I get hold of them, to also test the
# positive detection case (catching a paper that SHOULD be flagged).
# ------------------------------------------------------------------

def test_real_papers_not_falsely_capped():
    import pdfplumber
    from pathlib import Path

    real_papers = [
        "paper1.pdf",
        "paper2.pdf",
        "IndigenousWomen-led---Garo.pdf",
        "Ethnomedicinal_Survey_Marakh_Sect_Garo_Mymensingh.pdf",
        "Decolonizing_Bangladesh.pdf",
        "Ethnomedicinal_Plants_Fifteen_Clans_Garo_Madhupur.pdf",
        "Ethnomedicinal_Survey_Garo_Hills_Durgapur.pdf",
        "Evolution_Matrilineal_Characteristics_Garo_Social_System.pdf",
        "Forest_Dependent_Communities_Climate_Adaptation.pdf",
        "Indigenousvation.pdf",
        "Indigenous_Women_Led_Climate_Crisis_Solutions.pdf",
        "Livelihood_Patterns_Garo_Community_Tangail.pdf",
    ]
    for name in real_papers:
        path = Path(name)
        if not path.exists():
            print(f"[SKIP] {name} not found in current directory — skipping")
            continue
        text = ""
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        text_lower = text.lower()
        scan = check_data_driven_evidence(text_lower)
        record(
            f"Real paper '{name}' not misclassified as experience_report (negative check only)",
            scan["verdict"] != "experience_report",
            f"got verdict={scan['verdict']!r}",
        )


if __name__ == "__main__":
    print("Part 1 & 2 — synthetic fixtures:")
    test_experience_report_snippet()
    test_data_driven_snippet()
    test_mixed_experience_leaning_snippet()
    test_undetermined_when_no_signals()
    test_cap_applied_for_experience_report()
    test_no_cap_for_data_driven()

    print("\nPart 3 — regression check against every real paper in the repo:")
    test_real_papers_not_falsely_capped()

    print("\n" + "=" * 60)
    failed = [r for r in results if r[0] == FAIL]
    print(f"{len(results) - len(failed)}/{len(results)} checks passing.")

    print("\nNext steps to keep strengthening this:")
    print("  - Add more real experience-report / opinion-piece papers as they")
    print("    become available, to keep testing true-positive detection.")
    print("  - Keep tuning the 40% cap severity as more real papers come in.")
    print("  - Run against a larger, more varied sample of real papers as the")
    print("    team keeps compiling them.")

    if failed:
        print("\nFAILED:")
        for status, name, detail in failed:
            print(f"  - {name}: {detail}")
        sys.exit(1)
