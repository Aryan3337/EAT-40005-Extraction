#!/usr/bin/env python3
"""
confidence_framework.py  —  Version 5.0
=========================================
P85 – Mandi Climate Knowledge Graph Project  |  EAT40005 Capstone

Model-based Confidence Framework using Ollama + mistral-small3.1.

Replaces keyword scanning with contextual LLM evaluation for subjective
criteria (ICAT, domain relevance, structural quality, peer-review).
Objective criteria (metadata, red-flags) remain code-based.

Changes in v5.0
---------------
- LLM-based evaluation for Criteria 1-4 via Ollama
- Structured system prompt returns scored JSON with written justifications
- Justifications saved to rejection/review logs for full audit trail
- Hard-fail gates removed from code; incorporated into system prompt guidance
- Criteria 5-6 (metadata, red-flags) remain code-based (deterministic)

Usage
-----
    # Make sure Ollama is running: ollama serve
    python confidence_framework.py paper.pdf
    python confidence_framework.py paper.pdf --title "..." --year 2023 --journal "Nature"

Integration with script.py:
    from confidence_framework import run_confidence_check, EvaluationOutcome
    result = run_confidence_check(pdf_path, metadata)
    if result.passed:
        run_kg_extraction(pdf_path, model)

Exit codes:
    0 = APPROVED       → safe to pass to run_kg_extraction()
    2 = MANUAL REVIEW  → hold; check review_queue.csv
    1 = REJECTED       → skip; check rejection_logs/
"""

import sys
import csv
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional
import requests
import pdfplumber

# ============================================================
# Configuration
# ============================================================

OLLAMA_URL      = "http://localhost:11434/api/chat"
OLLAMA_MODEL    = "mistral:7b"

REJECT_THRESHOLD = 60   # score <  60        → REJECTED
REVIEW_THRESHOLD = 75   # score 60–75        → MANUAL REVIEW
                        # score >  75        → APPROVED

LOG_DIR           = Path("rejection_logs")
REVIEW_QUEUE_FILE = Path("review_queue.csv")

RED_FLAG_PHRASES: List[str] = [
    "blog post", "opinion piece", "press release", "news article",
    "wikipedia", "social media", "unreviewed",
]


# ============================================================
# Outcome enum
# ============================================================

class EvaluationOutcome(str, Enum):
    APPROVED      = "APPROVED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    REJECTED      = "REJECTED"


# ============================================================
# Data classes
# ============================================================

@dataclass
class CriterionResult:
    name:          str
    score:         int
    max_score:     int
    passed:        bool
    justification: str          # model's written reasoning
    evaluated_by:  str          # "model" or "code"
    flags:         List[str] = field(default_factory=list)


@dataclass
class EvaluationResult:
    paper_path:        str
    paper_name:        str
    timestamp:         str
    total_score:       int
    max_possible:      int
    outcome:           EvaluationOutcome
    criteria:          List[CriterionResult] = field(default_factory=list)
    rejection_reason:  Optional[str] = None
    review_reason:     Optional[str] = None
    log_path:          Optional[str] = None
    review_queue_path: Optional[str] = None
    model_used:        str = OLLAMA_MODEL

    @property
    def score_pct(self) -> float:
        return round(self.total_score / self.max_possible * 100, 1) if self.max_possible else 0.0

    @property
    def passed(self) -> bool:
        return self.outcome == EvaluationOutcome.APPROVED


# ============================================================
# 1. Text Extraction from PDF
#    Identical to script.py — same function signature and behaviour
# ============================================================

def extract_text_from_pdf(pdf_path: str) -> str:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text()
            if page_text:
                text += f"\n===== Page {page_num} =====\n"
                text += page_text + "\n"
    return text


# ============================================================
# 2. System prompt
#    Instructs the model to evaluate the paper and return
#    structured JSON scores + justifications for each criterion
# ============================================================

def build_system_prompt() -> str:
    return """You are an expert academic paper evaluator for the P85 Mandi Climate Knowledge Graph project at Swinburne University.

Your job is to assess whether a research paper is suitable for automated knowledge extraction about the Mandi/Garo Indigenous community of Bangladesh. You must evaluate the paper across four criteria and return a JSON response only — no prose, no markdown, no explanation outside the JSON.

## Project Context
This project preserves tacit climate and cultural knowledge of the Mandi (Garo) Indigenous community of Bangladesh. Papers must be academically credible, domain-relevant, and — critically — must handle Indigenous knowledge ethically. The ICAT (Indigenous Knowledge Attribution Toolkit) framework guides the ethical assessment.

## Criteria to Evaluate

### Criterion 1 — Structural Completeness (max 20 pts)
Does this document have the structure of a genuine research paper?
- Has a clear abstract, introduction, methodology/methods, results or findings, conclusion, and references
- Is substantive enough (not just an abstract or summary)
- Score 0-20 based on how complete and well-structured it is

### Criterion 2 — Peer-Review Quality (max 25 pts)
Does this appear to be a peer-reviewed academic publication?
- Published in a journal or conference proceedings
- Has a DOI, ISSN, volume/issue numbers, or received/accepted dates
- Uses formal academic language and citation practices
- Authors have institutional affiliations
- Has a rigorous methodology
- Score 0-25 based on strength of peer-review evidence

### Criterion 3 — Climate and Domain Relevance (max 15 pts)
Is this paper genuinely relevant to the Mandi/Garo community and climate knowledge?
- Discusses the Mandi or Garo community of Bangladesh
- Covers climate, environmental, agricultural, or seasonal knowledge
- Covers traditional, tacit, or Indigenous knowledge practices
- Score 0-15 based on how central and substantive this relevance is (not just a passing mention)

### Criterion 4 — Ethical Source Handling / ICAT (max 25 pts)
Does this paper handle Indigenous knowledge ethically? Assess each of the five ICAT checks (5 pts each):
a) Respectful, non-racist, non-colonial terminology used throughout
b) Author is Indigenous or the research is conducted in genuine community partnership
c) Informed consent was documented — participants agreed to be part of the research
d) The paper centres Indigenous ways of knowing rather than treating community as objects of study
e) The author's positionality or relationship to the knowledge is stated

Be contextually aware: consent may be described as "participants gave permission", "consent form", "right to withdraw", "audio-recorded after getting their permission" — not only as "informed consent". Award points based on evidence found, not just exact phrases.

Score 0-25. If consent (c) is completely absent with no evidence whatsoever, note this as a serious concern in your justification.

## Required JSON Output Format
Return only this JSON structure, with no text before or after it:

{
  "criteria": [
    {
      "name": "Structural Completeness",
      "score": <0-20>,
      "max_score": 20,
      "justification": "<2-3 sentences explaining the score>",
      "flags": ["<any specific concerns>"]
    },
    {
      "name": "Peer-Review Quality",
      "score": <0-25>,
      "max_score": 25,
      "justification": "<2-3 sentences explaining the score>",
      "flags": ["<any specific concerns>"]
    },
    {
      "name": "Climate and Domain Relevance",
      "score": <0-15>,
      "max_score": 15,
      "justification": "<2-3 sentences explaining the score>",
      "flags": ["<any specific concerns>"]
    },
    {
      "name": "Ethical Source Handling (ICAT)",
      "score": <0-25>,
      "max_score": 25,
      "justification": "<2-3 sentences explaining the score with specific evidence from the paper>",
      "flags": ["<list any failed ICAT checks or serious concerns>"]
    }
  ],
  "overall_recommendation": "<one sentence summary of suitability for Mandi community knowledge extraction>"
}"""


# Chunk size in words — keeps each request well within timeout limits
CHUNK_WORD_SIZE = 1500
CHUNK_OVERLAP   = 200

def chunk_paper(paper_text: str) -> List[str]:
    """Split paper into overlapping word chunks, mirroring script.py logic."""
    words  = paper_text.split()
    chunks = []
    start  = 0
    while start < len(words):
        end = min(start + CHUNK_WORD_SIZE, len(words))
        chunks.append(" ".join(words[start:end]))
        start += CHUNK_WORD_SIZE - CHUNK_OVERLAP
    return chunks


def build_user_prompt(chunk_text: str, metadata: Dict[str, Any], chunk_num: int, total_chunks: int) -> str:
    meta_str = "\n".join([
        f"Title: {metadata.get('title', 'Unknown')}",
        f"Authors: {metadata.get('authors', 'Unknown')}",
        f"Year: {metadata.get('year', 'Unknown')}",
        f"Journal: {metadata.get('journal', 'Unknown')}",
        f"DOI: {metadata.get('doi', 'Unknown')}",
    ])
    return f"""## Paper Metadata
{meta_str}

## Paper Excerpt (chunk {chunk_num} of {total_chunks})
{chunk_text}

Evaluate this excerpt against all four criteria and return only the JSON response."""


# ============================================================
# 3. Ollama API call
#    Follows same pattern as script.py's extract_triples_from_chunk()
# ============================================================

def call_ollama(system_prompt: str, user_prompt: str, retries: int = 2) -> Optional[str]:
    for attempt in range(retries):
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {"role": "system",  "content": system_prompt},
                        {"role": "user",    "content": user_prompt},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.1,   # low temp for consistent scoring
                        "num_predict": 2048,
                    }
                },
                timeout=300   # longer timeout — full paper evaluation takes time
            )
            if response.status_code == 200:
                return response.json().get("message", {}).get("content", "")
            print(f"   Ollama returned status {response.status_code} (attempt {attempt+1})")
            print(f"   Response: {response.text[:200]}")
        except requests.exceptions.ConnectionError:
            print("   Cannot connect to Ollama. Is 'ollama serve' running?")
            if attempt == retries - 1:
                return None
        except Exception as e:
            print(f"   Ollama error: {e}")
        time.sleep(2)
    return None


def parse_model_response(raw: str) -> Optional[List[Dict]]:
    """Extract and parse the JSON block from the model response."""
    # Strip any markdown code fences the model may have added
    cleaned = re.sub(r"```json|```", "", raw).strip()
    # Find the outermost JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
        return data.get("criteria", [])
    except json.JSONDecodeError:
        return None


# ============================================================
# 4. Model-based criteria evaluation (Criteria 1–4)
# ============================================================

def evaluate_with_model(paper_text: str, metadata: Dict[str, Any]) -> List[CriterionResult]:
    """
    Chunk the paper and evaluate each chunk separately via Ollama.
    Scores are averaged across chunks; justifications and flags are aggregated.
    Mirrors script.py chunking logic for consistency.
    """
    system_prompt = build_system_prompt()
    chunks        = chunk_paper(paper_text)
    total_chunks  = len(chunks)
    print(f"   Split into {total_chunks} chunks of ~{CHUNK_WORD_SIZE} words each.")

    expected = [
        ("Structural Completeness",        20),
        ("Peer-Review Quality",            25),
        ("Climate and Domain Relevance",   15),
        ("Ethical Source Handling (ICAT)", 25),
    ]

    # Accumulate scores, justifications, flags across chunks
    accumulated: Dict[str, Dict] = {
        name: {"scores": [], "justifications": [], "flags": [], "max_score": mx}
        for name, mx in expected
    }

    successful_chunks = 0
    for idx, chunk in enumerate(chunks, start=1):
        print(f"   Chunk {idx}/{total_chunks}...", end=" ", flush=True)
        user_prompt = build_user_prompt(chunk, metadata, idx, total_chunks)
        raw = call_ollama(system_prompt, user_prompt)
        if not raw:
            print("failed (skipped)")
            continue
        criteria_data = parse_model_response(raw)
        if not criteria_data:
            print("parse error (skipped)")
            continue

        successful_chunks += 1
        print(f"OK")
        for (name, _), item in zip(expected, criteria_data):
            accumulated[name]["scores"].append(int(item.get("score", 0)))
            accumulated[name]["justifications"].append(item.get("justification", ""))
            accumulated[name]["flags"].extend(item.get("flags", []))
        time.sleep(0.5)

    if successful_chunks == 0:
        print("   All chunks failed — falling back to zero scores.")
        return _fallback_criteria()

    print(f"   {successful_chunks}/{total_chunks} chunks evaluated successfully.")

    # Aggregate: take the MAX score across chunks (best evidence wins)
    # and combine all justifications and unique flags
    results = []
    for name, mx in expected:
        acc      = accumulated[name]
        scores   = acc["scores"]
        score    = max(0, min(max(scores) if scores else 0, mx))
        # Pick the justification from the highest-scoring chunk
        best_idx = scores.index(max(scores)) if scores else 0
        justification = acc["justifications"][best_idx] if acc["justifications"] else "No justification."
        unique_flags  = list(dict.fromkeys(acc["flags"]))  # deduplicate, preserve order

        results.append(CriterionResult(
            name          = name,
            score         = score,
            max_score     = mx,
            passed        = score > 0,
            justification = justification,
            evaluated_by  = "model",
            flags         = unique_flags,
        ))
    return results


def _fallback_criteria() -> List[CriterionResult]:
    """Return zero-scored criteria if model call fails."""
    specs = [
        ("Structural Completeness",        20),
        ("Peer-Review Quality",            25),
        ("Climate and Domain Relevance",   15),
        ("Ethical Source Handling (ICAT)", 25),
    ]
    return [
        CriterionResult(
            name          = name,
            score         = 0,
            max_score     = max_pts,
            passed        = False,
            justification = "Model evaluation failed — could not connect to Ollama or parse response.",
            evaluated_by  = "fallback",
            flags         = ["Model unavailable"],
        )
        for name, max_pts in specs
    ]


# ============================================================
# 5. Code-based criteria (Criteria 5–6 — deterministic)
# ============================================================

def check_metadata_completeness(metadata: Dict[str, Any]) -> CriterionResult:
    field_scores = {"title": 3, "authors": 2, "year": 2, "journal": 2, "doi": 1}
    score   = sum(pts for f, pts in field_scores.items() if metadata.get(f))
    found   = [f for f in field_scores if metadata.get(f)]
    missing = [f for f in field_scores if not metadata.get(f)]
    return CriterionResult(
        name          = "Metadata Completeness",
        score         = score,
        max_score     = 10,
        passed        = score >= 5,
        justification = f"Metadata present: {found}. Missing: {missing}.",
        evaluated_by  = "code",
        flags         = [f"Missing: {m}" for m in missing] if missing else [],
    )


def check_red_flags(text_lower: str) -> CriterionResult:
    found = [f for f in RED_FLAG_PHRASES if f in text_lower]
    score = max(0, 5 - len(found) * 3)
    return CriterionResult(
        name          = "Red-Flag Absence",
        score         = score,
        max_score     = 5,
        passed        = True,
        justification = f"Red-flag phrases found: {found}." if found else "No red-flag phrases detected.",
        evaluated_by  = "code",
        flags         = [f"Red flag: '{f}'" for f in found],
    )


# ============================================================
# 6. Output writers
# ============================================================

def save_evaluation_log(result: EvaluationResult, log_type: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\-]", "_", Path(result.paper_path).stem)[:50]
    log_path  = LOG_DIR / f"{result.timestamp}_{log_type}_{safe_name}.json"

    data = {
        "paper":           result.paper_path,
        "paper_name":      result.paper_name,
        "timestamp":       result.timestamp,
        "model_used":      result.model_used,
        "outcome":         result.outcome.value,
        "total_score":     result.total_score,
        "max_possible":    result.max_possible,
        "score_pct":       result.score_pct,
        "thresholds": {
            "reject_below":       REJECT_THRESHOLD,
            "manual_review_band": f"{REJECT_THRESHOLD}-{REVIEW_THRESHOLD}",
            "auto_approve_above": REVIEW_THRESHOLD,
        },
        "rejection_reason": result.rejection_reason,
        "review_reason":    result.review_reason,
        "criteria": [
            {
                "name":          c.name,
                "score":         c.score,
                "max_score":     c.max_score,
                "passed":        c.passed,
                "evaluated_by":  c.evaluated_by,
                "justification": c.justification,
                "flags":         c.flags,
            }
            for c in result.criteria
        ],
        "next_steps": (
            "REJECTED — paper skipped. Review the model justifications above for each criterion "
            "to understand why this paper did not meet the required standard."
            if log_type == "rejection"
            else
            "MANUAL REVIEW — extraction is held. A team member should read the model justifications, "
            "particularly for ICAT, before deciding to approve or reject this paper."
        ),
    }
    log_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return log_path


def append_review_queue(result: EvaluationResult) -> Path:
    write_header = not REVIEW_QUEUE_FILE.exists()
    with open(REVIEW_QUEUE_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow([
                "timestamp", "paper_name", "paper_path", "model_used",
                "score", "score_pct", "icat_justification",
                "icat_flags", "review_reason",
                "status", "override_by", "override_note",
            ])
        icat = next((c for c in result.criteria if "ICAT" in c.name), None)
        writer.writerow([
            result.timestamp,
            result.paper_name,
            result.paper_path,
            result.model_used,
            result.total_score,
            result.score_pct,
            icat.justification if icat else "",
            "; ".join(icat.flags) if icat else "",
            result.review_reason,
            "PENDING",
            "",
            "",
        ])
    return REVIEW_QUEUE_FILE


# ============================================================
# 7. Main pipeline function
#    run_confidence_check() — sits before run_kg_extraction()
# ============================================================

def run_confidence_check(
    pdf_path: str,
    metadata: Optional[Dict[str, Any]] = None,
    override_approve: Optional[str] = None,
) -> EvaluationResult:
    """
    Run confidence checks on a paper using Ollama + mistral-small3.1.

    Integration with script.py:
        result = run_confidence_check(pdf_path, metadata)
        if result.passed:
            run_kg_extraction(pdf_path, model)
    """
    paper_path = Path(pdf_path)
    paper_name = paper_path.stem
    metadata   = metadata or {}
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Manual override ───────────────────────────────────────────────────
    if override_approve:
        print(f"[OVERRIDE] {paper_name} manually approved: {override_approve}")
        return EvaluationResult(
            paper_path    = str(paper_path),
            paper_name    = paper_name,
            timestamp     = timestamp,
            total_score   = -1,
            max_possible  = 100,
            outcome       = EvaluationOutcome.APPROVED,
            review_reason = f"Manual override: {override_approve}",
        )

    print(f"1. Extracting text from {paper_name}...")
    try:
        full_text  = extract_text_from_pdf(str(paper_path))
        text_lower = full_text.lower()
        print(f"   Extracted {len(text_lower.split())} words.")
    except Exception as e:
        print(f"   Text extraction failed: {e}")
        full_text  = ""
        text_lower = ""

    print("2. Running model evaluation (Criteria 1–4)...")
    model_criteria = evaluate_with_model(full_text, metadata)

    print("3. Running code evaluation (Criteria 5–6)...")
    code_criteria = [
        check_metadata_completeness(metadata),
        check_red_flags(text_lower),
    ]
    for c in code_criteria:
        print(f"   {c.name}: {c.score}/{c.max_score}")

    all_criteria  = model_criteria + code_criteria
    total_score   = sum(c.score for c in all_criteria)
    max_possible  = sum(c.max_score for c in all_criteria)

    # ── Determine outcome ─────────────────────────────────────────────────
    if total_score < REJECT_THRESHOLD:
        outcome          = EvaluationOutcome.REJECTED
        rejection_reason = (
            f"Total score {total_score}/{max_possible} ({round(total_score/max_possible*100,1)}%) "
            f"is below the reject threshold of {REJECT_THRESHOLD}%."
        )
        review_reason = None
    elif total_score <= REVIEW_THRESHOLD:
        outcome          = EvaluationOutcome.MANUAL_REVIEW
        rejection_reason = None
        review_reason    = (
            f"Score {total_score}/{max_possible} ({round(total_score/max_possible*100,1)}%) "
            f"is in the manual review band ({REJECT_THRESHOLD}-{REVIEW_THRESHOLD}). "
            f"Check model justifications in the review log before proceeding."
        )
    else:
        outcome          = EvaluationOutcome.APPROVED
        rejection_reason = None
        review_reason    = None

    result = EvaluationResult(
        paper_path       = str(paper_path),
        paper_name       = paper_name,
        timestamp        = timestamp,
        total_score      = total_score,
        max_possible     = max_possible,
        outcome          = outcome,
        criteria         = all_criteria,
        rejection_reason = rejection_reason,
        review_reason    = review_reason,
        model_used       = OLLAMA_MODEL,
    )

    # ── Write outputs ─────────────────────────────────────────────────────
    if outcome == EvaluationOutcome.REJECTED:
        log_path        = save_evaluation_log(result, "rejection")
        result.log_path = str(log_path)
        print(f"4. REJECTED — {rejection_reason}")
        print(f"   Log: {log_path}")

    elif outcome == EvaluationOutcome.MANUAL_REVIEW:
        log_path             = save_evaluation_log(result, "review")
        result.log_path      = str(log_path)
        rq_path              = append_review_queue(result)
        result.review_queue_path = str(rq_path)
        print(f"4. MANUAL REVIEW — {review_reason}")
        print(f"   Log: {log_path}")
        print(f"   Review queue: {rq_path}")

    else:
        print(f"4. APPROVED — score {total_score}/{max_possible} ({result.score_pct}%)")

    print("Done!")
    return result


# ============================================================
# 8. CLI
# ============================================================

def _print_result(r: EvaluationResult) -> None:
    ICONS = {
        EvaluationOutcome.APPROVED:      "APPROVED",
        EvaluationOutcome.MANUAL_REVIEW: "MANUAL REVIEW",
        EvaluationOutcome.REJECTED:      "REJECTED",
    }
    print(f"\n{'='*65}")
    print(f"{ICONS[r.outcome]}  —  {r.paper_name}")
    print(f"Model: {r.model_used}")
    if r.total_score >= 0:
        print(f"Score: {r.total_score}/100 ({r.score_pct}%)")
        print(f"Bands: REJECTED < {REJECT_THRESHOLD}  |  "
              f"MANUAL REVIEW {REJECT_THRESHOLD}-{REVIEW_THRESHOLD}  |  "
              f"APPROVED > {REVIEW_THRESHOLD}")
    print("-" * 65)
    for c in r.criteria:
        tag = "MODEL" if c.evaluated_by == "model" else "CODE "
        status = "OK" if c.passed else "LOW"
        print(f"  [{tag}] [{status}]  {c.name}: {c.score}/{c.max_score}")
        print(f"           {c.justification}")
        for fl in c.flags:
            print(f"           FLAG: {fl}")
        print()
    if r.rejection_reason:
        print(f"Reason:       {r.rejection_reason}")
    if r.review_reason:
        print(f"Reason:       {r.review_reason}")
        print(f"Review queue: {r.review_queue_path}")
    if r.log_path:
        print(f"Log:          {r.log_path}")
    print("=" * 65)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="P85 Confidence Framework v5.0 — model-based evaluation via Ollama"
    )
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--title",            default="")
    parser.add_argument("--authors",          default="")
    parser.add_argument("--year",             default="")
    parser.add_argument("--journal",          default="")
    parser.add_argument("--doi",              default="")
    parser.add_argument("--model",            default=OLLAMA_MODEL,
                        help=f"Ollama model to use (default: {OLLAMA_MODEL})")
    parser.add_argument("--override-approve", default=None,
                        help="Manually approve a MANUAL_REVIEW paper with a justification string")
    args = parser.parse_args()

    meta = {
        "title":   args.title,
        "authors": [a.strip() for a in args.authors.split(",")] if args.authors else [],
        "year":    args.year,
        "journal": args.journal,
        "doi":     args.doi,
    }

    # Allow model override via CLI
    OLLAMA_MODEL = args.model

    result = run_confidence_check(
        args.pdf_path,
        metadata         = meta,
        override_approve = args.override_approve,
    )
    _print_result(result)

    sys.exit(
        0 if result.outcome == EvaluationOutcome.APPROVED      else
        2 if result.outcome == EvaluationOutcome.MANUAL_REVIEW else
        1
    )