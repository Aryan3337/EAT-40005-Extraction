"""Tests for admin_ingest.py -- the admin upload path.

An admin drops a PDF in the web UI, it is scored by the confidence framework,
and what happens next depends on the verdict:

    APPROVED       -> stored, queued as ready to extract
    MANUAL_REVIEW  -> stored, held
    REJECTED       -> NOT stored, the admin is told why

Extraction itself is not started here. At the measured 157.3 s/chunk a
22-page paper is 2.2 hours, and the hosted container has no GPU, so a human
runs the CLI against the queue.

The fourth case is the one the confidence framework gets wrong on its own.
When Ollama is unreachable or its JSON will not parse, _fallback_criteria()
zeroes all four model-scored criteria -- 85 of the available points -- and
the paper is written to confidence_logs/rejected/ as REJECTED. An
infrastructure failure is recorded as an editorial verdict, indistinguishable
from a rejection on merit. This module must not inherit that: a paper whose
scoring failed is held, not rejected.
"""

import json

import pytest

from admin_ingest import (
    IngestDecision,
    check_admin_secret,
    decide,
    ingest_pdf,
    safe_pdf_name,
)


# -- test doubles -------------------------------------------------------------


class FakeCriterion:
    def __init__(self, evaluated_by="model", flags=None, justification="ok"):
        self.evaluated_by = evaluated_by
        self.flags = flags or []
        self.justification = justification
        self.name = "Peer-Review Quality"
        self.score = 20
        self.max_score = 25


class FakeResult:
    """Shaped like confidence_framework.EvaluationResult."""

    def __init__(self, outcome, total_score=80, criteria=None,
                 rejection_reason=None, review_reason=None):
        self.paper_name = "garo_4"
        self.paper_path = "uploads/garo_4.pdf"
        self.outcome = outcome
        self.total_score = total_score
        self.max_possible = 100
        self.criteria = criteria if criteria is not None else [FakeCriterion()]
        self.rejection_reason = rejection_reason
        self.review_reason = review_reason

    @property
    def passed(self):
        return self.outcome == "APPROVED"


PDF_BYTES = b"%PDF-1.4 fake"


# -- decide -------------------------------------------------------------------


def test_an_approved_paper_is_ready_to_extract():
    assert decide(FakeResult("APPROVED")) is IngestDecision.READY_TO_EXTRACT


def test_a_review_paper_is_held():
    assert decide(FakeResult("MANUAL_REVIEW", total_score=65)) is IngestDecision.HELD_FOR_REVIEW


def test_a_rejected_paper_is_rejected():
    assert decide(FakeResult("REJECTED", total_score=40)) is IngestDecision.REJECTED


def test_a_paper_whose_scoring_failed_is_held_not_rejected():
    # THE important one. _fallback_criteria marks every criterion
    # evaluated_by="fallback" when the model call fails, and the framework
    # then reports REJECTED at a near-zero score. Treating that as an
    # editorial rejection would discard a paper because Ollama was down.
    failed = FakeResult(
        "REJECTED",
        total_score=5,
        criteria=[FakeCriterion(evaluated_by="fallback", flags=["Model unavailable"])],
    )
    assert decide(failed) is IngestDecision.SCORING_FAILED


def test_a_genuine_rejection_is_not_mistaken_for_a_failure():
    # A real low score with model-evaluated criteria stays a rejection.
    genuine = FakeResult(
        "REJECTED",
        total_score=40,
        criteria=[FakeCriterion(evaluated_by="model")],
    )
    assert decide(genuine) is IngestDecision.REJECTED


def test_a_partial_scoring_failure_still_counts_as_failure():
    # If any criterion fell back, the total is not a verdict we can trust.
    mixed = FakeResult(
        "REJECTED",
        total_score=30,
        criteria=[FakeCriterion(evaluated_by="model"),
                  FakeCriterion(evaluated_by="fallback", flags=["Model unavailable"])],
    )
    assert decide(mixed) is IngestDecision.SCORING_FAILED


# -- safe_pdf_name ------------------------------------------------------------


@pytest.mark.parametrize("hostile", [
    "../../etc/passwd.pdf",
    "..\\..\\windows\\system32\\evil.pdf",
    "/absolute/path.pdf",
    "C:\\Windows\\x.pdf",
    "....//....//x.pdf",
])
def test_a_filename_cannot_escape_the_upload_directory(hostile):
    name = safe_pdf_name(hostile)
    assert "/" not in name and "\\" not in name
    assert not name.startswith(".")
    assert ".." not in name


def test_a_normal_filename_survives_recognisably():
    assert safe_pdf_name("garo_4.pdf") == "garo_4.pdf"


def test_spaces_and_awkward_characters_are_normalised():
    name = safe_pdf_name("My Paper (final) v2.pdf")
    assert name.endswith(".pdf")
    assert " " not in name


def test_a_non_pdf_extension_is_refused():
    # The confidence framework reads PDFs; anything else is a mistake or an
    # attempt to put an arbitrary file on the server.
    with pytest.raises(ValueError, match="PDF"):
        safe_pdf_name("notes.txt")


def test_an_empty_filename_is_refused():
    with pytest.raises(ValueError):
        safe_pdf_name("")


# -- check_admin_secret -------------------------------------------------------


def test_the_right_secret_is_accepted():
    assert check_admin_secret("hunter2-long-random", expected="hunter2-long-random")


def test_a_wrong_secret_is_refused():
    assert not check_admin_secret("nope", expected="hunter2-long-random")


def test_no_secret_configured_refuses_everything():
    # Fails CLOSED. A deployment that forgot to set ADMIN_UPLOAD_SECRET must
    # not end up with an upload endpoint open to anyone who finds the URL.
    assert not check_admin_secret("anything", expected=None)
    assert not check_admin_secret("anything", expected="")
    assert not check_admin_secret("", expected="")


def test_a_missing_header_is_refused():
    assert not check_admin_secret(None, expected="hunter2-long-random")


# -- ingest_pdf ---------------------------------------------------------------


def test_an_approved_paper_is_stored_and_queued(tmp_path):
    outcome = ingest_pdf(
        PDF_BYTES, "garo_4.pdf",
        scorer=lambda path: FakeResult("APPROVED"),
        uploads_dir=tmp_path,
    )

    assert outcome.decision is IngestDecision.READY_TO_EXTRACT
    assert outcome.stored_path is not None
    assert (tmp_path / "papers" / "garo_4.pdf").read_bytes() == PDF_BYTES

    entries = [json.loads(line) for line in
               (tmp_path / "queue.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    assert entries[0]["decision"] == "ready_to_extract"
    assert entries[0]["paper"] == "garo_4.pdf"
    assert entries[0]["score"] == 80


def test_a_review_paper_is_stored_and_queued(tmp_path):
    outcome = ingest_pdf(
        PDF_BYTES, "garo_4.pdf",
        scorer=lambda path: FakeResult("MANUAL_REVIEW", total_score=65),
        uploads_dir=tmp_path,
    )

    assert outcome.decision is IngestDecision.HELD_FOR_REVIEW
    assert (tmp_path / "papers" / "garo_4.pdf").exists()


def test_a_rejected_paper_is_not_kept(tmp_path):
    outcome = ingest_pdf(
        PDF_BYTES, "garo_4.pdf",
        scorer=lambda path: FakeResult("REJECTED", total_score=40,
                                       rejection_reason="No peer review"),
        uploads_dir=tmp_path,
    )

    assert outcome.decision is IngestDecision.REJECTED
    assert outcome.stored_path is None
    assert not (tmp_path / "papers" / "garo_4.pdf").exists()
    assert "No peer review" in " ".join(outcome.reasons)


def test_a_rejection_is_still_recorded_in_the_queue(tmp_path):
    # The file is discarded; the decision is not. An admin has to be able to
    # see that a paper was submitted and turned down, and why.
    ingest_pdf(
        PDF_BYTES, "garo_4.pdf",
        scorer=lambda path: FakeResult("REJECTED", total_score=40),
        uploads_dir=tmp_path,
    )

    entries = [json.loads(line) for line in
               (tmp_path / "queue.jsonl").read_text(encoding="utf-8").splitlines()]
    assert entries[0]["decision"] == "rejected"


def test_a_scoring_failure_keeps_the_file(tmp_path):
    # Discarding on an infrastructure failure would mean the admin has to
    # re-upload once Ollama is back.
    outcome = ingest_pdf(
        PDF_BYTES, "garo_4.pdf",
        scorer=lambda path: FakeResult(
            "REJECTED", total_score=5,
            criteria=[FakeCriterion(evaluated_by="fallback", flags=["Model unavailable"])]),
        uploads_dir=tmp_path,
    )

    assert outcome.decision is IngestDecision.SCORING_FAILED
    assert (tmp_path / "papers" / "garo_4.pdf").exists()
    assert any("scor" in r.lower() for r in outcome.reasons)


def test_a_scorer_that_raises_is_a_scoring_failure_not_a_rejection(tmp_path):
    # Ollama refusing the connection raises rather than returning a result.
    def exploding_scorer(path):
        raise ConnectionError("Cannot connect to Ollama")

    outcome = ingest_pdf(PDF_BYTES, "garo_4.pdf",
                         scorer=exploding_scorer, uploads_dir=tmp_path)

    assert outcome.decision is IngestDecision.SCORING_FAILED
    assert (tmp_path / "papers" / "garo_4.pdf").exists()
    assert any("Ollama" in r for r in outcome.reasons)


def test_a_second_upload_of_the_same_name_does_not_overwrite_the_first(tmp_path):
    scorer = lambda path: FakeResult("APPROVED")
    first = ingest_pdf(PDF_BYTES, "garo_4.pdf", scorer=scorer, uploads_dir=tmp_path)
    second = ingest_pdf(b"%PDF-1.4 different", "garo_4.pdf", scorer=scorer,
                        uploads_dir=tmp_path)

    assert first.stored_path != second.stored_path
    assert (tmp_path / "papers" / "garo_4.pdf").read_bytes() == PDF_BYTES


def test_an_empty_upload_is_refused_before_scoring(tmp_path):
    # Scoring an empty file wastes minutes of inference to conclude nothing.
    called = []

    def scorer(path):
        called.append(path)
        return FakeResult("APPROVED")

    with pytest.raises(ValueError):
        ingest_pdf(b"", "garo_4.pdf", scorer=scorer, uploads_dir=tmp_path)

    assert called == []


def test_something_that_is_not_a_pdf_is_refused_before_scoring(tmp_path):
    called = []

    def scorer(path):
        called.append(path)
        return FakeResult("APPROVED")

    with pytest.raises(ValueError, match="PDF"):
        ingest_pdf(b"<html>hello</html>", "garo_4.pdf",
                   scorer=scorer, uploads_dir=tmp_path)

    assert called == []


def test_the_queue_survives_a_rejected_paper_and_keeps_order(tmp_path):
    for outcome_name, score in [("APPROVED", 80), ("REJECTED", 40), ("MANUAL_REVIEW", 65)]:
        ingest_pdf(PDF_BYTES, f"paper_{score}.pdf",
                   scorer=lambda path, o=outcome_name, s=score: FakeResult(o, total_score=s),
                   uploads_dir=tmp_path)

    entries = [json.loads(line) for line in
               (tmp_path / "queue.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["decision"] for e in entries] == \
        ["ready_to_extract", "rejected", "held_for_review"]


# -- validate_upload ----------------------------------------------------------


def test_validate_upload_returns_the_safe_name():
    from admin_ingest import validate_upload

    assert validate_upload(PDF_BYTES, "../../garo_4.pdf") == "garo_4.pdf"


@pytest.mark.parametrize("data,filename", [
    (b"", "garo_4.pdf"),
    (b"<html>", "garo_4.pdf"),
    (PDF_BYTES, "notes.txt"),
    (PDF_BYTES, ""),
])
def test_validate_upload_rejects_what_ingest_would_reject(data, filename):
    # The HTTP layer calls this synchronously so a bad upload gets an
    # immediate 400 rather than a 202 and silence.
    from admin_ingest import validate_upload

    with pytest.raises(ValueError):
        validate_upload(data, filename)
