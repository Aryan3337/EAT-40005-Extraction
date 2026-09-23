"""Deterministic well-formedness/readability check: flags (never deletes) a
triple whose Subject, Predicate, or Object looks like a mis-split sentence
fragment rather than a clean entity/relationship name. No LLM call -- purely
structural/shape checks; semantic garbling is instead caught by the strict
prompt's readability rule and the verify pass's third question. See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §6.2."""

from dataclasses import dataclass, field

from verification.text_utils import split_camel_case

MAX_ENTITY_WORDS = 4
MAX_PREDICATE_WORDS = 3
DANGLING_LEADING_WORDS = {"the", "a", "an", "of", "in", "on", "at", "and", "or"}


@dataclass
class WellformednessResult:
    flagged: bool
    reasons: list[str] = field(default_factory=list)


def _check_entity(label: str, name: str) -> list[str]:
    words = split_camel_case(name)
    reasons = []
    if len(words) > MAX_ENTITY_WORDS:
        reasons.append(f"{label} '{name}' has {len(words)} words (max {MAX_ENTITY_WORDS})")
    if words and (words[0] in DANGLING_LEADING_WORDS or words[-1] in DANGLING_LEADING_WORDS):
        reasons.append(f"{label} '{name}' starts or ends on a dangling word")
    return reasons


def check_wellformedness(subject: str, predicate: str, obj: str) -> WellformednessResult:
    reasons = _check_entity("Subject", subject) + _check_entity("Object", obj)

    predicate_segments = [segment for segment in predicate.strip().split("_") if segment]
    if len(predicate_segments) > MAX_PREDICATE_WORDS:
        reasons.append(
            f"Predicate '{predicate}' has {len(predicate_segments)} segments "
            f"(max {MAX_PREDICATE_WORDS}) -- looks like a clause, not a relation name"
        )

    return WellformednessResult(flagged=bool(reasons), reasons=reasons)
