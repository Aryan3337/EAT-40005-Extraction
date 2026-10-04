"""The admin upload path: a PDF arrives, gets scored, and is kept or not.

An admin drops a paper in the web UI. It is scored by the confidence
framework, and the verdict decides what happens:

    APPROVED       -> stored, queued as ready to extract
    MANUAL_REVIEW  -> stored, held
    REJECTED       -> NOT stored, the admin is told why

Extraction is deliberately NOT started here. Measured at 157.3 s/chunk, a
22-page paper is 2.2 hours of inference, and the hosted container has no GPU
and no job queue. A human runs the CLI against the queue this writes.

THE FOURTH CASE. The confidence framework cannot distinguish "this paper is
poor" from "the scorer was unreachable": when the Ollama call fails or its
JSON will not parse, `_fallback_criteria()` zeroes all four model-scored
criteria -- 85 of the 100 available points -- and the paper is written to
`confidence_logs/rejected/` as REJECTED at a score of about 5. Three of
`paper1`'s six recorded rejections are exactly this. Inheriting that would
mean discarding an admin's upload because a service was down, and telling
them their paper failed on merit. So a scoring failure is its own decision
here: the file is KEPT and the admin is told to retry, never rejected.

This module does no HTTP and no authentication beyond checking a shared
secret, so all of it is testable without a server or a live model.
"""

import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

# A real PDF starts with this. Checked before scoring, because scoring spends
# minutes of inference to discover that a file was never a paper.
PDF_MAGIC = b"%PDF"


class IngestDecision(str, Enum):
    READY_TO_EXTRACT = "ready_to_extract"
    HELD_FOR_REVIEW = "held_for_review"
    REJECTED = "rejected"
    SCORING_FAILED = "scoring_failed"


@dataclass
class IngestOutcome:
    decision: IngestDecision
    paper: str
    score: int | None = None
    max_score: int | None = None
    outcome: str | None = None
    reasons: list[str] = field(default_factory=list)
    stored_path: str | None = None

    @property
    def stored(self) -> bool:
        return self.stored_path is not None

    def to_json(self) -> dict:
        return {
            "decision": self.decision.value,
            "paper": self.paper,
            "score": self.score,
            "max_score": self.max_score,
            "outcome": self.outcome,
            "reasons": self.reasons,
            "stored_path": self.stored_path,
        }


def check_admin_secret(provided: str | None, *, expected: str | None) -> bool:
    """Fails closed.

    A deployment that forgot to set ADMIN_UPLOAD_SECRET must not end up with
    an upload endpoint open to anyone who finds the URL, so an unset or empty
    expected secret refuses everything rather than waving everything through.
    compare_digest keeps the check constant-time.
    """
    if not expected or not provided:
        return False
    return secrets.compare_digest(provided, expected)


def safe_pdf_name(filename: str) -> str:
    """Reduce an uploaded filename to a bare, safe PDF name.

    The filename comes from the browser, so it is attacker-controlled. Taking
    only the final path component and stripping anything that is not
    alphanumeric, dot, dash or underscore means a name cannot climb out of
    the uploads directory or hide as a dotfile.
    """
    if not filename or not filename.strip():
        raise ValueError("A filename is required.")

    # Split on both separators: the browser may send either.
    base = re.split(r"[\\/]", filename.strip())[-1]
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).lstrip(".")

    if not base.lower().endswith(".pdf"):
        raise ValueError(
            f"Only PDF uploads are accepted; got {filename!r}. The confidence "
            f"framework reads PDFs."
        )
    stem = base[: -len(".pdf")].replace(".", "_")
    if not stem:
        raise ValueError("A filename is required.")
    return f"{stem}.pdf"


def _scoring_failed(result) -> bool:
    """True when the score reflects an unreachable model, not a judgement.

    `_fallback_criteria()` marks every criterion it fabricates
    `evaluated_by="fallback"`. If ANY criterion fell back, the total is not a
    verdict we can act on.
    """
    return any(
        getattr(criterion, "evaluated_by", "") == "fallback"
        for criterion in getattr(result, "criteria", []) or []
    )


def decide(result) -> IngestDecision:
    """Map a confidence-framework result onto what to do with the file."""
    if _scoring_failed(result):
        return IngestDecision.SCORING_FAILED

    outcome = str(getattr(result, "outcome", "")).upper()
    if outcome.endswith("APPROVED"):
        return IngestDecision.READY_TO_EXTRACT
    if outcome.endswith("MANUAL_REVIEW"):
        return IngestDecision.HELD_FOR_REVIEW
    return IngestDecision.REJECTED


def _reasons_from(result, decision: IngestDecision) -> list[str]:
    reasons = []
    if decision is IngestDecision.SCORING_FAILED:
        reasons.append(
            "Scoring did not complete -- the confidence model was unreachable "
            "or returned something unparseable. The paper has been kept; try "
            "again once Ollama is running. This is NOT a judgement on the paper."
        )
    for attribute in ("rejection_reason", "review_reason"):
        value = getattr(result, attribute, None)
        if value:
            reasons.append(str(value))
    if decision is IngestDecision.REJECTED and not reasons:
        reasons.append("Scored below the approval threshold.")
    return reasons


def _unique_path(directory: Path, name: str) -> Path:
    """Never overwrite an earlier upload: two papers can share a filename."""
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = name[: -len(".pdf")], ".pdf"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    counter = 0
    while True:
        extra = f"-{counter}" if counter else ""
        candidate = directory / f"{stem}-{stamp}{extra}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def validate_upload(data: bytes, filename: str) -> str:
    """Check an upload is usable and return its safe name, or raise ValueError.

    Separate from ingest_pdf so the HTTP layer can reject a bad upload
    synchronously, with a 400 the admin sees straight away, before handing the
    slow scoring work to a background thread.
    """
    name = safe_pdf_name(filename)
    if not data:
        raise ValueError("The uploaded file is empty.")
    if not data.startswith(PDF_MAGIC):
        raise ValueError(
            "That file is not a PDF -- it does not start with %PDF. Scoring it "
            "would spend minutes of inference to conclude the same thing."
        )
    return name


def ingest_pdf(data: bytes, filename: str, *, scorer, uploads_dir) -> IngestOutcome:
    """Score an uploaded PDF and keep or discard it accordingly.

    `scorer` takes a path and returns a confidence-framework EvaluationResult.
    It is injected so this is testable without a live model; the server passes
    `confidence_framework.run_confidence_check`.

    The file is written before scoring because the scorer reads from disk, and
    removed again if the verdict is a genuine rejection.
    """
    uploads_dir = Path(uploads_dir)
    name = validate_upload(data, filename)

    papers_dir = uploads_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    stored = _unique_path(papers_dir, name)
    stored.write_bytes(data)

    try:
        result = scorer(str(stored))
    except Exception as error:
        # An unreachable Ollama raises rather than returning a low score. Same
        # class as the fallback case: keep the file, do not call it rejected.
        outcome = IngestOutcome(
            decision=IngestDecision.SCORING_FAILED,
            paper=name,
            reasons=[
                f"Scoring did not complete: {type(error).__name__}: {error}. "
                f"The paper has been kept; try again once the confidence model "
                f"is reachable. This is NOT a judgement on the paper."
            ],
            stored_path=str(stored),
        )
        _append_to_queue(uploads_dir, outcome)
        return outcome

    decision = decide(result)
    outcome = IngestOutcome(
        decision=decision,
        paper=name,
        score=getattr(result, "total_score", None),
        max_score=getattr(result, "max_possible", None),
        outcome=str(getattr(result, "outcome", "")) or None,
        reasons=_reasons_from(result, decision),
        stored_path=str(stored),
    )

    if decision is IngestDecision.REJECTED:
        stored.unlink(missing_ok=True)
        outcome.stored_path = None

    _append_to_queue(uploads_dir, outcome)
    return outcome


def _append_to_queue(uploads_dir: Path, outcome: IngestOutcome) -> Path:
    """Append-only log of every decision, including rejections.

    A rejected file is discarded but its decision is not: an admin has to be
    able to see that a paper was submitted and turned down, and why.
    """
    uploads_dir.mkdir(parents=True, exist_ok=True)
    queue_path = uploads_dir / "queue.jsonl"
    entry = outcome.to_json()
    entry["at"] = datetime.now(timezone.utc).isoformat()
    with open(queue_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return queue_path


def read_queue(uploads_dir) -> list[dict]:
    """Every decision so far, oldest first. Returns [] when nothing is queued."""
    queue_path = Path(uploads_dir) / "queue.jsonl"
    if not queue_path.exists():
        return []
    entries = []
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            # One corrupt line must not hide the rest of the queue.
            continue
    return entries
