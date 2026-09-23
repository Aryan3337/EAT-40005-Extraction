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


from dataclasses import dataclass
from typing import Callable


def _greedy_match(extracted: list[Triple], ground_truth: list[Triple],
                   match_fn: Callable[[Triple, Triple], bool]) -> tuple[int, int, int]:
    """One-to-one greedy matching: each ground-truth triple can be claimed by
    at most one extracted triple, in extracted-list order. Not a globally
    optimal (Hungarian-algorithm) matching -- deterministic and sufficient at
    the small per-page triple counts this project works with."""
    claimed_gt: set[int] = set()
    matched_extracted = 0
    for extracted_triple in extracted:
        for gt_index, gt_triple in enumerate(ground_truth):
            if gt_index in claimed_gt:
                continue
            if match_fn(extracted_triple, gt_triple):
                claimed_gt.add(gt_index)
                matched_extracted += 1
                break
    true_positives = matched_extracted
    false_positives = len(extracted) - matched_extracted
    false_negatives = len(ground_truth) - len(claimed_gt)
    return true_positives, false_positives, false_negatives


def _precision_recall_f1(true_positives: int, false_positives: int, false_negatives: int) -> tuple[float, float, float]:
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


@dataclass
class ScoreReport:
    tp_strict: int
    fp_strict: int
    fn_strict: int
    tp_lenient: int
    fp_lenient: int
    fn_lenient: int
    precision_strict: float
    recall_strict: float
    f1_strict: float
    precision_lenient: float
    recall_lenient: float
    f1_lenient: float
    hallucination_rate: float
    triples_per_page: float


def score(extracted: list[Triple], ground_truth: list[Triple], num_pages: int) -> ScoreReport:
    tp_strict, fp_strict, fn_strict = _greedy_match(extracted, ground_truth, match_strict)
    tp_lenient, fp_lenient, fn_lenient = _greedy_match(extracted, ground_truth, match_lenient)
    precision_strict, recall_strict, f1_strict = _precision_recall_f1(tp_strict, fp_strict, fn_strict)
    precision_lenient, recall_lenient, f1_lenient = _precision_recall_f1(tp_lenient, fp_lenient, fn_lenient)
    hallucination_rate = fp_strict / len(extracted) if extracted else 0.0
    triples_per_page = len(extracted) / num_pages if num_pages else 0.0
    return ScoreReport(
        tp_strict=tp_strict, fp_strict=fp_strict, fn_strict=fn_strict,
        tp_lenient=tp_lenient, fp_lenient=fp_lenient, fn_lenient=fn_lenient,
        precision_strict=precision_strict, recall_strict=recall_strict, f1_strict=f1_strict,
        precision_lenient=precision_lenient, recall_lenient=recall_lenient, f1_lenient=f1_lenient,
        hallucination_rate=hallucination_rate, triples_per_page=triples_per_page,
    )
