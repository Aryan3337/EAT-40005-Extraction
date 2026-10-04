"""Runs the three deterministic gates over a list of triples, in one place.

Both callers go through this module: run_verification_pipeline.py (CSV in,
CSV out, for offline analysis) and main.py (in-memory dicts, straight on to
Neo4j). Before this existed the loop was copied per caller, which is how the
gates and their hard-gate semantics could have drifted apart between the
offline numbers in the docs and what the live pipeline actually enforced.

The gates are a HARD gate, not an advisory flag: a flagged row is excluded
from `kept` outright. This pipeline feeds a fully autonomous chatbot with no
human review step, so anything not confidently correct is dropped rather than
held for someone to look at. Every rejected row is still recorded under the
gate that caught it -- and under ALL of them if several did, since the flag
files are an audit trail, not a first-match-wins dispatch.

No LLM calls here: the whole pass runs in about a second over a few hundred
rows.
"""

import re
from dataclasses import dataclass, field

from verification.grounding_check import check_grounding
from verification.quote_check import check_quote_genuine
from verification.wellformedness_check import check_wellformedness

WELLFORMEDNESS = "wellformedness"
GROUNDING = "grounding"
QUOTE = "quote"


@dataclass
class GateOutcome:
    """`kept` is the survivors, in input order. `flagged` maps a gate name to
    the rows it rejected, each a copy of the input row plus a `flag_reason`;
    a gate that rejected nothing is absent rather than mapped to an empty
    list, so `if not outcome.flagged` reads as "nothing was rejected"."""

    kept: list[dict] = field(default_factory=list)
    flagged: dict[str, list[dict]] = field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "refined": len(self.kept),
            "wellformedness_flags": len(self.flagged.get(WELLFORMEDNESS, [])),
            "grounding_flags": len(self.flagged.get(GROUNDING, [])),
            "quote_flags": len(self.flagged.get(QUOTE, [])),
        }


def page_number_from_source_section(source_section: str | None) -> str:
    """kg_extractor.py's triples carry source_section='Page N' (a string),
    not a raw page_number column -- the quote gate needs an int-parseable
    page number per row to look up that page's text in the source PDF."""
    match = re.search(r"\d+", source_section or "")
    return match.group() if match else "0"


def sentence_for_row(row: dict) -> str:
    """The citation a row is judged against. sentence_ref is the intended
    field; passage is the fallback for rows where the model dropped the '// '
    prefix on its SENTENCE REF line and kg_extractor's parser dumped the lot
    into passage instead."""
    return row.get("sentence_ref") or row.get("passage") or ""


def _page_text_for_row(row: dict, page_texts: dict[int, str]) -> str:
    """Fails closed: a row with a missing or unparseable page_number gets an
    empty page, which the quote gate then rejects. A row whose provenance we
    cannot even locate is exactly the kind that must not reach the graph, and
    one malformed row should not raise and take the whole run down."""
    try:
        return page_texts.get(int(row.get("page_number", "")), "")
    except (TypeError, ValueError):
        return ""


def apply_gates(
    rows: list[dict],
    *,
    wellformedness: bool = True,
    grounding: bool = True,
    quote: bool = False,
    page_texts: dict[int, str] | None = None,
) -> GateOutcome:
    """Run the enabled gates over `rows` and split them into kept/flagged.

    `quote` needs `page_texts` (from eval.hallucination.load_page_texts) --
    it checks each row's citation against its own page of the source PDF.
    """
    if quote and page_texts is None:
        raise ValueError(
            "the quote gate requires page_texts -- it checks each row's "
            "sentence_ref against its own page of the source PDF. Pass "
            "page_texts=load_page_texts(pdf_path)."
        )

    outcome = GateOutcome()

    for row in rows:
        subject, predicate, obj = row["subject"], row["predicate"], row["object"]
        sentence = sentence_for_row(row)
        rejected = False

        checks = []
        if wellformedness:
            checks.append((WELLFORMEDNESS, check_wellformedness(subject, predicate, obj)))
        if grounding:
            checks.append((GROUNDING, check_grounding(subject, obj, sentence)))
        if quote:
            page_text = _page_text_for_row(row, page_texts)
            checks.append((QUOTE, check_quote_genuine(sentence, page_text)))

        for gate_name, result in checks:
            if not result.flagged:
                continue
            rejected = True
            flagged_row = dict(row)
            flagged_row["flag_reason"] = "; ".join(result.reasons)
            outcome.flagged.setdefault(gate_name, []).append(flagged_row)

        if not rejected:
            outcome.kept.append(row)

    return outcome
