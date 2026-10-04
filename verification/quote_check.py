"""Deterministic quote-genuineness check: flags a triple whose sentence_ref
isn't actually present, verbatim, on its own page of the source PDF --
catches a fabricated quote wrapped around an otherwise-plausible claim (the
extractor inventing a citation, not just a fact). check_grounding
(grounding_check.py) cannot catch this on its own: it only checks the
triple's Subject/Object words against sentence_ref itself, so a triple whose
sentence_ref is entirely made up can still look "grounded" against its own
invented quote."""

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass
class QuoteResult:
    flagged: bool
    reasons: list[str] = field(default_factory=list)


def normalize_for_quote_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _segments(span: str) -> list[str]:
    """Splits a span on '...'/'…' -- a common truncation habit (a long
    sentence shortened with a trailing ellipsis). Each segment must
    independently be a genuine substring of the page: this accepts real
    truncation (one segment, a true prefix/suffix) while still rejecting a
    fabrication spliced onto a real fragment (the invented segment fails on
    its own)."""
    parts = re.split(r"\.\.\.|…", span)
    return [p.strip() for p in parts if p.strip()]


def _spans(sentence_ref: str) -> list[str]:
    """A sentence_ref may hold one or more '<...>'-quoted spans plus
    '// SENTENCE REF:' continuation noise (see kg_extractor.py's output
    shape); falls back to the whole string, quote-stripped, when there are
    no angle brackets at all."""
    cleaned = re.sub(r"//\s*SENTENCE REF:\s*", " ", sentence_ref)
    spans = re.findall(r"<([^<>]+)>", cleaned)
    if not spans:
        stripped = cleaned.strip().strip('"').strip()
        spans = [stripped] if stripped else []
    return spans


def check_quote_genuine(sentence_ref: str, page_text: str) -> QuoteResult:
    if not sentence_ref or not sentence_ref.strip():
        return QuoteResult(
            flagged=True,
            reasons=["No sentence_ref provided -- cannot verify it's a real quote"],
        )

    spans = _spans(sentence_ref)
    if not spans:
        return QuoteResult(
            flagged=True,
            reasons=["sentence_ref has no quoted span to check"],
        )

    normalized_page = normalize_for_quote_match(page_text)
    reasons = []
    for span in spans:
        segments = _segments(span)
        if not segments:
            reasons.append(f"Quoted span not found verbatim on this page: {span[:80]!r}")
            continue
        for segment in segments:
            if normalize_for_quote_match(segment) not in normalized_page:
                reasons.append(f"Quoted span not found verbatim on this page: {segment[:80]!r}")

    return QuoteResult(flagged=bool(reasons), reasons=reasons)
