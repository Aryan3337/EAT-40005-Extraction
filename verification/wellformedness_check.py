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
# Words that restate the same concept rather than distinguishing it -- e.g.
# "Different types of baskets" vs "Types of baskets" is the same entity, not
# a real relationship. Stripped before comparing Subject/Object word sets.
TAUTOLOGY_QUALIFIER_WORDS = {"different", "various", "several", "some", "many", "certain", "of", "the", "a", "an"}


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


def _core_words(name: str) -> set[str]:
    return {word for word in split_camel_case(name) if word not in TAUTOLOGY_QUALIFIER_WORDS}


def _check_tautology(subject: str, obj: str) -> list[str]:
    subject_core = _core_words(subject)
    object_core = _core_words(obj)
    if subject_core and subject_core == object_core:
        return [f"Subject '{subject}' and Object '{obj}' are tautological (same concept restated)"]
    return []


def check_wellformedness(subject: str, predicate: str, obj: str) -> WellformednessResult:
    reasons = (
        _check_entity("Subject", subject)
        + _check_entity("Object", obj)
        + _check_tautology(subject, obj)
    )

    predicate_segments = [segment for segment in predicate.strip().split("_") if segment]
    if len(predicate_segments) > MAX_PREDICATE_WORDS:
        reasons.append(
            f"Predicate '{predicate}' has {len(predicate_segments)} segments "
            f"(max {MAX_PREDICATE_WORDS}) -- looks like a clause, not a relation name"
        )

    return WellformednessResult(flagged=bool(reasons), reasons=reasons)
