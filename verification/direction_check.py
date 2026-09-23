"""Deterministic direction/ontology check: flags a triple whose Subject/Object
keyword shape looks reversed against a curated predicate-direction lexicon.
No LLM call, flag-only (never deletes). See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §6.1."""

from dataclasses import dataclass

from verification.predicate_directions import DIRECTIONAL_PREDICATES


@dataclass
class DirectionResult:
    flagged: bool
    reason: str | None = None


def _contains_any(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in keywords)


def check_direction(subject: str, predicate: str, obj: str) -> DirectionResult:
    entry = DIRECTIONAL_PREDICATES.get(predicate.strip().upper())
    if entry is None:
        return DirectionResult(flagged=False)

    subject_looks_like_object = _contains_any(subject, entry["object_keywords"])
    object_looks_like_subject = _contains_any(obj, entry["subject_keywords"])

    if subject_looks_like_object and object_looks_like_subject:
        return DirectionResult(
            flagged=True,
            reason=(
                f"{predicate}: subject '{subject}' matches expected object-side "
                f"keywords and object '{obj}' matches expected subject-side "
                f"keywords -- direction looks reversed."
            ),
        )
    return DirectionResult(flagged=False)
