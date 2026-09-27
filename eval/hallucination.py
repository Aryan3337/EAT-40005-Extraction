"""Computes a grounding-based hallucination rate for extracted triples: the
fraction whose citation is either not a genuine quote from its own page
(quote_check) or doesn't textually support the claim (grounding_check).

This is deliberately independent of scorer.py's ground-truth matching.
Ground-truth matching answers "did this triple happen to match one human's
page-level ground-truth sheet" -- a triple can fail that (and so count
against precision/recall there) while being entirely real and grounded in
the source text, just phrased differently or covering something the human
sheet didn't enumerate. This module answers a different question: "is this
triple's claim actually supported by the text it cites", independent of
whether any human happened to write it down. See scorer.py's `gt_miss_rate`
for the ground-truth-comparison metric this is not a replacement for."""

import csv
from dataclasses import dataclass, field

import pdfplumber

from verification.grounding_check import check_grounding
from verification.quote_check import check_quote_genuine


def load_page_texts(pdf_path: str) -> dict[int, str]:
    with pdfplumber.open(pdf_path) as pdf:
        return {i + 1: (page.extract_text() or "") for i, page in enumerate(pdf.pages)}


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check_row_hallucinated(row: dict, page_texts: dict[int, str]) -> list[str]:
    """Returns the reasons a single extracted row is considered hallucinated,
    or [] if it passes both the quote-genuineness and grounding checks.
    Fails closed: an unknown/missing page counts as ungrounded, same as
    grounding_check's own empty-sentence_ref handling."""
    page_number = int(row["page_number"])
    page_text = page_texts.get(page_number, "")
    sentence_ref = row.get("sentence_ref", "")

    reasons = []
    reasons.extend(check_quote_genuine(sentence_ref, page_text).reasons)
    reasons.extend(check_grounding(row["subject"], row["object"], sentence_ref).reasons)
    return reasons


@dataclass
class HallucinationReport:
    flagged_count: int
    total_count: int
    hallucination_rate: float
    citation_coverage: float
    flagged_rows: list[dict] = field(default_factory=list)


def compute_hallucination_rate(rows: list[dict], page_texts: dict[int, str]) -> HallucinationReport:
    """`hallucination_rate` fails closed: a row with no usable sentence_ref
    counts as flagged, same as grounding_check's own empty-ref handling --
    there's no evidence it's grounded, so it isn't. But that means the rate
    alone can't distinguish "genuinely ungrounded claims" from "this
    extraction path never captures citations at all" (a real, observed
    failure mode -- see the live/test_extraction.py prompt path, which
    populates 0/35 sentence_ref on garo_1 page 3). Always read
    `citation_coverage` alongside `hallucination_rate`: a low coverage means
    the rate is resting on a thin evidence base, not a confident measurement."""
    flagged_rows = []
    with_citation = 0
    for row in rows:
        if row.get("sentence_ref", "").strip():
            with_citation += 1
        reasons = check_row_hallucinated(row, page_texts)
        if reasons:
            flagged_rows.append({**row, "reasons": reasons})

    total = len(rows)
    flagged = len(flagged_rows)
    rate = flagged / total if total else 0.0
    coverage = with_citation / total if total else 0.0
    return HallucinationReport(
        flagged_count=flagged, total_count=total,
        hallucination_rate=rate, citation_coverage=coverage,
        flagged_rows=flagged_rows,
    )
