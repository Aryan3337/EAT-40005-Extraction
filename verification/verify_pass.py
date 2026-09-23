"""Two-step verification pass: checks one candidate triple for evidence,
tacit-ness, and readability (prompts/verify_tacit_evidence_v1.txt) via a
pluggable judge_fn. The real backend is Ollama-only (zero marginal cost --
see docs/superpowers/specs/2026-09-21-extraction-verification-design.md
§1.2, §5)."""

import json
import os
import re
from dataclasses import dataclass
from typing import Callable

import requests

from prompts.loader import load_prompt_template

VERIFY_LOW_THRESHOLD = 0.35
VERIFY_HIGH_THRESHOLD = 0.7

OLLAMA_VERIFY_URL = os.environ.get("OLLAMA_VERIFY_URL", "http://localhost:11434/api/generate")

JudgeFn = Callable[[str, str, str, str], tuple[str, float, str]]


@dataclass
class VerifyResult:
    band: str  # "keep", "review", or "reject"
    decision: str
    confidence: float
    reason: str


def _parse_judge_response(text: str) -> tuple[str, float, str]:
    # On a parse failure, confidence falls back to 0.5 (not 0.0) so the
    # result bands to "review" rather than "reject" -- a parse failure is
    # not evidence the triple is bad, and must not silently delete it with
    # no audit trail (spec S5: ambiguous outcomes are held for a human, not
    # silently dropped). Mirrors pruner/llm_judge.py's _parse_response,
    # which uses the same 0.5 fallback for the same reason.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return "reject", 0.5, "unparseable_judge_response"
    try:
        data = json.loads(match.group(0))
        return (
            str(data.get("decision", "reject")),
            float(data.get("confidence", 0.0)),
            str(data.get("reason", "")),
        )
    except (ValueError, json.JSONDecodeError):
        return "reject", 0.5, "unparseable_judge_response"


def judge_with_ollama(subject: str, predicate: str, obj: str, source_sentence: str,
                       model: str = "deepseek-r1:7b") -> tuple[str, float, str]:
    """Real backend -- local Ollama only, no paid API. Not unit tested (requires
    a live Ollama call); exercised manually per spec §10."""
    template = load_prompt_template("verify_tacit_evidence_v1")
    prompt = (
        template.replace("{source_sentence}", source_sentence)
        .replace("{subject}", subject)
        .replace("{predicate}", predicate)
        .replace("{object}", obj)
    )
    response = requests.post(
        OLLAMA_VERIFY_URL,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=60,
    )
    response.raise_for_status()
    return _parse_judge_response(response.json().get("response", ""))


def verify_triple(subject: str, predicate: str, obj: str, source_sentence: str,
                   judge_fn: JudgeFn) -> VerifyResult:
    decision, confidence, reason = judge_fn(subject, predicate, obj, source_sentence)
    if confidence < VERIFY_LOW_THRESHOLD:
        band = "reject"
    elif confidence >= VERIFY_HIGH_THRESHOLD:
        band = "keep"
    else:
        band = "review"
    # A high-confidence "keep" band whose decision explicitly says "reject"
    # is a contradiction the prompt tries to prevent but doesn't guarantee
    # against. Fail safe toward the audit trail, not toward silent
    # acceptance: downgrade to "review" rather than trusting confidence alone.
    if band == "keep" and decision.strip().lower() == "reject":
        band = "review"
    return VerifyResult(band=band, decision=decision, confidence=confidence, reason=reason)
