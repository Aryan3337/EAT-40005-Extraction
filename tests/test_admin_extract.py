"""Covers POST /admin/extract -- the wire between an approved paper and main.py.

Everything either side of this already existed: the confidence framework
scores an upload and routes it, a reviewer can read the PDF and approve it,
and main.py extracts, gates and uploads to Neo4j on its own. Nothing read
the `ready_to_extract` state, so an approved paper sat in uploads/ forever.

What this endpoint must refuse matters more than what it accepts. The human
gate in this system is at paper ADMISSION -- once a paper is approved its
gated triples go straight into the production graph with no triple-level
review. So a paper that was rejected, or is still waiting for a human, must
not be extractable by asking for it directly.
"""

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import extract_jobs
import rag
from rag import create_query_handler


@pytest.fixture()
def extract_request(monkeypatch, tmp_path):
    """POSTs to /admin/extract as an authenticated admin, against tmp_path."""
    monkeypatch.setattr(rag, "UPLOADS_DIR", tmp_path)
    monkeypatch.setenv("ADMIN_UPLOAD_SECRET", "s3cret")

    started: list = []

    def fake_begin(paper, **kwargs):
        started.append(paper)
        return True

    monkeypatch.setattr(extract_jobs, "begin", fake_begin)

    handler_cls = create_query_handler(object(), object())

    def post(paper, *, role="admin", secret="s3cret"):
        raw = json.dumps({"paper": paper}).encode("utf-8")
        handler = handler_cls.__new__(handler_cls)
        handler.path = "/admin/extract"
        handler.headers = {
            "Content-Length": str(len(raw)),
            "X-Admin-Secret": secret,
        }
        handler.rfile = io.BytesIO(raw)
        handler._authenticated_user = lambda: {"email": "a@b.c", "role": role}
        sent = {}
        handler._send_json = lambda status, payload: sent.update(
            status=status, payload=payload
        )
        handler.do_POST()
        return sent, started

    return post


def _store(tmp_path, name):
    papers = tmp_path / "papers"
    papers.mkdir(parents=True, exist_ok=True)
    (papers / name).write_bytes(b"%PDF-1.4 fake")


def test_an_approved_paper_starts_extracting(extract_request, tmp_path):
    _store(tmp_path, "garo_2.pdf")
    extract_jobs._append(tmp_path, {"paper": "garo_2.pdf",
                                    "decision": "ready_to_extract"})

    sent, started = extract_request("garo_2.pdf")

    assert sent["status"] == 202, sent
    assert started == ["garo_2.pdf"]


def test_a_non_admin_cannot_start_an_extraction(extract_request, tmp_path):
    _store(tmp_path, "garo_2.pdf")
    extract_jobs._append(tmp_path, {"paper": "garo_2.pdf",
                                    "decision": "ready_to_extract"})

    sent, started = extract_request("garo_2.pdf", role="user")

    assert sent["status"] == 403
    assert started == []


def test_a_wrong_admin_secret_cannot_start_an_extraction(extract_request, tmp_path):
    _store(tmp_path, "garo_2.pdf")
    extract_jobs._append(tmp_path, {"paper": "garo_2.pdf",
                                    "decision": "ready_to_extract"})

    sent, started = extract_request("garo_2.pdf", secret="wrong")

    assert sent["status"] == 401
    assert started == []


def test_an_unknown_paper_is_not_found(extract_request):
    sent, started = extract_request("never_uploaded.pdf")

    assert sent["status"] == 404
    assert started == []


def test_a_paper_still_awaiting_review_is_refused(extract_request, tmp_path):
    """Extracting this would bypass the only human gate in the system."""
    _store(tmp_path, "contested.pdf")
    extract_jobs._append(tmp_path, {"paper": "contested.pdf",
                                    "decision": "held_for_review"})

    sent, started = extract_request("contested.pdf")

    assert sent["status"] == 409
    assert started == []


def test_a_rejected_paper_is_refused(extract_request, tmp_path):
    """A manual rejection keeps the file on disk, so the PDF existing is not
    permission to extract it."""
    _store(tmp_path, "rejected.pdf")
    extract_jobs._append(tmp_path, {"paper": "rejected.pdf",
                                    "decision": "rejected"})

    sent, started = extract_request("rejected.pdf")

    assert sent["status"] == 409
    assert started == []


def test_a_second_extraction_is_refused_while_one_runs(
    extract_request, tmp_path, monkeypatch
):
    """begin() owns the one-at-a-time rule; the endpoint reports its answer."""
    _store(tmp_path, "garo_2.pdf")
    extract_jobs._append(tmp_path, {"paper": "garo_2.pdf",
                                    "decision": "ready_to_extract"})
    monkeypatch.setattr(extract_jobs, "begin", lambda paper, **kwargs: False)

    sent, _ = extract_request("garo_2.pdf")

    assert sent["status"] == 409
    assert "already" in sent["payload"]["error"].lower()


def test_a_request_without_a_paper_is_a_bad_request(extract_request):
    sent, started = extract_request("")

    assert sent["status"] == 400
    assert started == []


@pytest.fixture()
def review_request(monkeypatch, tmp_path):
    """POSTs an approve/deny to /admin/review as an authenticated admin."""
    monkeypatch.setattr(rag, "UPLOADS_DIR", tmp_path)
    monkeypatch.setenv("ADMIN_UPLOAD_SECRET", "s3cret")

    started: list = []
    monkeypatch.setattr(extract_jobs, "begin",
                        lambda paper, **kwargs: started.append(paper) or True)

    handler_cls = create_query_handler(object(), object())

    def post(paper, approve):
        raw = json.dumps({"paper": paper, "approve": approve}).encode("utf-8")
        handler = handler_cls.__new__(handler_cls)
        handler.path = "/admin/review"
        handler.headers = {"Content-Length": str(len(raw)),
                           "X-Admin-Secret": "s3cret"}
        handler.rfile = io.BytesIO(raw)
        handler._authenticated_user = lambda: {"email": "a@b.c", "role": "admin"}
        sent = {}
        handler._send_json = lambda status, payload: sent.update(
            status=status, payload=payload)
        handler.do_POST()
        return sent, started

    return post


def test_approving_a_held_paper_starts_extraction(review_request, tmp_path):
    """The point of the whole change: approval is what kicks extraction off,
    not a second button the admin has to remember to press."""
    _store(tmp_path, "contested.pdf")

    sent, started = review_request("contested.pdf", approve=True)

    assert sent["status"] == 200, sent
    assert started == ["contested.pdf"]


def test_denying_a_held_paper_starts_nothing(review_request, tmp_path):
    _store(tmp_path, "contested.pdf")

    sent, started = review_request("contested.pdf", approve=False)

    assert sent["status"] == 200, sent
    assert started == []


def test_start_extraction_if_ready_ignores_a_paper_that_is_not_stored(
    monkeypatch, tmp_path
):
    """An automatic rejection never stored the file. Nothing to extract."""
    monkeypatch.setattr(rag, "UPLOADS_DIR", tmp_path)
    monkeypatch.setattr(extract_jobs, "begin",
                        lambda paper, **kwargs: pytest.fail("must not start"))

    assert rag.start_extraction_if_ready("ghost.pdf") is False


def test_startup_reaps_an_extraction_a_restart_abandoned(monkeypatch, tmp_path):
    """docker compose up during a run would otherwise leave the paper stuck
    on 'extracting' forever, and the one-at-a-time rule would then refuse
    every later paper. Proves the hook reads the configured uploads dir."""
    monkeypatch.setattr(rag, "UPLOADS_DIR", tmp_path)
    stale = datetime.now(timezone.utc) - timedelta(hours=5)
    (tmp_path / "queue.jsonl").write_text(
        json.dumps({"paper": "garo_2.pdf", "decision": "extracting",
                    "at": stale.isoformat(), "by": "extraction"}) + "\n",
        encoding="utf-8")

    rag.reap_stale_extractions()

    state = extract_jobs.state_for("garo_2.pdf", uploads_dir=tmp_path)
    assert state["decision"] == "extraction_failed"
