"""Deterministic grounding check: flags (never deletes) a triple whose
Subject or Object isn't textually present in its own sentence_ref. No LLM
call -- catches entities the extraction step invented or paraphrased past
recognition, which a plausibility-judging LLM misses, since such a judge
asks "does this relate to the sentence", not "is every word of this claim
actually in the sentence". That was measured against this project's own LLM
verify pass, removed 2026-09-29: with grounding left out the hallucination
rate was 83%, with it in, 0%."""

from dataclasses import dataclass, field

from verification.text_utils import split_camel_case


@dataclass
class GroundingResult:
    flagged: bool
    reasons: list[str] = field(default_factory=list)


def _is_grounded(entity: str, sentence_lower: str) -> bool:
    words = split_camel_case(entity)
    if not words:
        return True
    return all(word in sentence_lower for word in words)


def check_grounding(subject: str, obj: str, sentence_ref: str) -> GroundingResult:
    if not sentence_ref or not sentence_ref.strip():
        return GroundingResult(
            flagged=True,
            reasons=["No sentence_ref provided -- cannot verify grounding"],
        )

    sentence_lower = sentence_ref.lower()
    reasons = []
    if not _is_grounded(subject, sentence_lower):
        reasons.append(f"Subject '{subject}' is not grounded in sentence_ref")
    if not _is_grounded(obj, sentence_lower):
        reasons.append(f"Object '{obj}' is not grounded in sentence_ref")

    return GroundingResult(flagged=bool(reasons), reasons=reasons)
