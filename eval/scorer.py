"""Scores extracted triples against ground truth: strict (exact) and lenient
(Jaccard token-overlap) matching. See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §7.2, §7.4."""

from verification.text_utils import split_camel_case

Triple = tuple[str, str, str]

LENIENT_THRESHOLD = 0.3


def normalize(subject: str, predicate: str, obj: str) -> Triple:
    return subject.strip().lower(), predicate.strip().lower(), obj.strip().lower()


def _tokens(triple: Triple) -> set[str]:
    subject, predicate, obj = triple
    predicate_tokens = [t for t in predicate.lower().replace("-", "_").split("_") if t]
    return set(split_camel_case(subject)) | set(predicate_tokens) | set(split_camel_case(obj))


def jaccard_similarity(a: Triple, b: Triple) -> float:
    tokens_a, tokens_b = _tokens(a), _tokens(b)
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def match_strict(a: Triple, b: Triple) -> bool:
    return normalize(*a) == normalize(*b)


def match_lenient(a: Triple, b: Triple, threshold: float = LENIENT_THRESHOLD) -> bool:
    return jaccard_similarity(a, b) >= threshold
