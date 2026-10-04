"""Deterministic grounding check: flags (never deletes) a triple whose
Subject or Object isn't textually present in its own sentence_ref. No LLM
call -- catches entities the extraction step invented or paraphrased past
recognition, which a plausibility-judging LLM misses, since such a judge
asks "does this relate to the sentence", not "is every word of this claim
actually in the sentence". That was measured against this project's own LLM
verify pass, removed 2026-09-29: with grounding left out the hallucination
rate was 83%, with it in, 0%.

Also bounds the citation's LENGTH (added 2026-10-04). A sentence_ref is meant
to be the one sentence a triple was read from, and exact-match grounding gets
easier to satisfy the longer that citation runs -- a paragraph restates so many
words that almost any entity in it counts as grounded. That is not theoretical:
on the 2026-09-29 garo_1.pdf run, 4 of 17 surviving triples shared a single
772-char, five-sentence paragraph as their citation and all 4 passed grounding,
while the correctly-cited population triple was rejected for quoting too
tightly. Over-rejecting a precise citation costs recall; under-rejecting a
verbose one ships a wrong fact, so the bound errs toward rejection."""

from dataclasses import dataclass, field

from verification.text_utils import split_camel_case

# Longest citation among the 13 sound survivors of the 2026-09-29 run was 132
# chars; the paragraph-cited defects were 772. The ceiling sits in that gap.
MAX_SENTENCE_REF_CHARS = 200


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

    citation_length = len(sentence_ref.strip())
    if citation_length > MAX_SENTENCE_REF_CHARS:
        reasons.append(
            f"sentence_ref is {citation_length} chars (max "
            f"{MAX_SENTENCE_REF_CHARS}) -- looks like a paragraph, not the "
            f"single sentence the triple was read from"
        )

    if not _is_grounded(subject, sentence_lower):
        reasons.append(f"Subject '{subject}' is not grounded in sentence_ref")
    if not _is_grounded(obj, sentence_lower):
        reasons.append(f"Object '{obj}' is not grounded in sentence_ref")

    return GroundingResult(flagged=bool(reasons), reasons=reasons)
