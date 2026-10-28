"""Tests for extract_jobs.py -- the state of an extraction run.

Extraction is a ~72-minute subprocess, so the admin screen can only ever see
a state, never a return value. That state lives in the same append-only
queue.jsonl the confidence framework writes to: one file, one audit trail,
and admin_ingest.current_queue already collapses it to latest-per-paper,
which is exactly what the Flutter queue list renders.
"""

import json
from datetime import datetime, timedelta, timezone

import extract_jobs


def test_start_records_the_paper_as_extracting(tmp_path):
    extract_jobs.start("garo_2.pdf", uploads_dir=tmp_path)

    state = extract_jobs.state_for("garo_2.pdf", uploads_dir=tmp_path)

    assert state["decision"] == "extracting"


def test_finish_records_the_triple_count(tmp_path):
    extract_jobs.start("garo_2.pdf", uploads_dir=tmp_path)

    extract_jobs.finish("garo_2.pdf", triples_loaded=212, uploads_dir=tmp_path)

    state = extract_jobs.state_for("garo_2.pdf", uploads_dir=tmp_path)
    assert state["decision"] == "extracted"
    assert state["triples_loaded"] == 212


def test_zero_triples_is_an_outcome_not_a_failure(tmp_path):
    """No triple surviving the three gates is the gates working, not a crash."""
    extract_jobs.start("thin.pdf", uploads_dir=tmp_path)

    extract_jobs.finish("thin.pdf", triples_loaded=0, uploads_dir=tmp_path)

    state = extract_jobs.state_for("thin.pdf", uploads_dir=tmp_path)
    assert state["decision"] == "extracted"
    assert state["triples_loaded"] == 0


def test_fail_records_the_error(tmp_path):
    extract_jobs.start("garo_2.pdf", uploads_dir=tmp_path)

    extract_jobs.fail("garo_2.pdf", error="Ollama refused", uploads_dir=tmp_path)

    state = extract_jobs.state_for("garo_2.pdf", uploads_dir=tmp_path)
    assert state["decision"] == "extraction_failed"
    assert "Ollama refused" in state["error"]


def test_state_for_an_unknown_paper_is_none(tmp_path):
    assert extract_jobs.state_for("never_seen.pdf", uploads_dir=tmp_path) is None


def test_the_audit_trail_keeps_every_state(tmp_path):
    """start then finish must leave both entries; the queue is append-only."""
    extract_jobs.start("garo_2.pdf", uploads_dir=tmp_path)
    extract_jobs.finish("garo_2.pdf", triples_loaded=5, uploads_dir=tmp_path)

    lines = (tmp_path / "queue.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def _write_entry(tmp_path, paper, decision, age_hours):
    """An entry aged by hand, so staleness can be tested without waiting."""
    at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    entry = {"paper": paper, "decision": decision,
             "at": at.isoformat(), "by": "extraction"}
    with open(tmp_path / "queue.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def test_reap_marks_a_long_dead_extraction_as_failed(tmp_path):
    """A container restart mid-run would otherwise wedge the paper forever:
    its latest state stays 'extracting' and nothing will ever clear it."""
    _write_entry(tmp_path, "garo_2.pdf", "extracting", age_hours=5)

    reaped = extract_jobs.reap_stale(uploads_dir=tmp_path)

    assert reaped == ["garo_2.pdf"]
    state = extract_jobs.state_for("garo_2.pdf", uploads_dir=tmp_path)
    assert state["decision"] == "extraction_failed"
    assert "restart" in state["error"].lower()


def test_reap_leaves_a_running_extraction_alone(tmp_path):
    """72 minutes is normal. Reaping at 30 would kill healthy runs."""
    _write_entry(tmp_path, "garo_2.pdf", "extracting", age_hours=0.5)

    assert extract_jobs.reap_stale(uploads_dir=tmp_path) == []
    state = extract_jobs.state_for("garo_2.pdf", uploads_dir=tmp_path)
    assert state["decision"] == "extracting"


def test_reap_ignores_a_finished_extraction(tmp_path):
    _write_entry(tmp_path, "garo_2.pdf", "extracted", age_hours=99)

    assert extract_jobs.reap_stale(uploads_dir=tmp_path) == []


def test_reap_ignores_a_paper_merely_waiting_to_be_extracted(tmp_path):
    """ready_to_extract is not a running job; it is a paper nobody started."""
    _write_entry(tmp_path, "garo_2.pdf", "ready_to_extract", age_hours=99)

    assert extract_jobs.reap_stale(uploads_dir=tmp_path) == []


def test_reap_on_an_empty_queue_is_a_no_op(tmp_path):
    assert extract_jobs.reap_stale(uploads_dir=tmp_path) == []


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_a_successful_run_records_the_count_neo4j_reported(tmp_path):
    """add_triples prints 'Uploaded N triples to Neo4j.' -- that line is the
    only honest source for the count, because it is what actually landed."""
    def runner(cmd, **kwargs):
        return _FakeCompleted(stdout="Uploaded 212 triples to Neo4j.\n  run_id=abc")

    extract_jobs.run_extraction("garo_2.pdf", pdf_path=tmp_path / "garo_2.pdf",
                                uploads_dir=tmp_path, runner=runner)

    state = extract_jobs.state_for("garo_2.pdf", uploads_dir=tmp_path)
    assert state["decision"] == "extracted"
    assert state["triples_loaded"] == 212


def test_a_run_that_uploads_nothing_is_extracted_with_zero(tmp_path):
    """'No triples survived the verification gates' exits 0. The gates did
    their job; that is a result, not a failure."""
    def runner(cmd, **kwargs):
        return _FakeCompleted(
            stdout="No triples survived the verification gates. Nothing to upload.")

    extract_jobs.run_extraction("thin.pdf", pdf_path=tmp_path / "thin.pdf",
                                uploads_dir=tmp_path, runner=runner)

    state = extract_jobs.state_for("thin.pdf", uploads_dir=tmp_path)
    assert state["decision"] == "extracted"
    assert state["triples_loaded"] == 0


def test_a_crashed_run_records_the_failure_with_stderr(tmp_path):
    def runner(cmd, **kwargs):
        return _FakeCompleted(returncode=1, stderr="ConnectionRefusedError: ollama")

    extract_jobs.run_extraction("garo_2.pdf", pdf_path=tmp_path / "garo_2.pdf",
                                uploads_dir=tmp_path, runner=runner)

    state = extract_jobs.state_for("garo_2.pdf", uploads_dir=tmp_path)
    assert state["decision"] == "extraction_failed"
    assert "ollama" in state["error"]


def test_the_gates_are_never_skipped(tmp_path):
    """NECTAR_BACKLOG.md: the human gate is at paper admission, so the three
    deterministic gates are load-bearing. No path here may pass --no-gates."""
    seen = {}

    def runner(cmd, **kwargs):
        seen["cmd"] = cmd
        return _FakeCompleted(stdout="Uploaded 1 triples to Neo4j.")

    extract_jobs.run_extraction("garo_2.pdf", pdf_path=tmp_path / "garo_2.pdf",
                                uploads_dir=tmp_path, runner=runner)

    assert "--no-gates" not in seen["cmd"]
    assert "main.py" in " ".join(seen["cmd"])


def test_a_run_marks_the_paper_extracting_before_it_starts(tmp_path):
    """The admin polls during the 72 minutes; the state has to exist then."""
    during = {}

    def runner(cmd, **kwargs):
        during["state"] = extract_jobs.state_for("garo_2.pdf", uploads_dir=tmp_path)
        return _FakeCompleted(stdout="Uploaded 3 triples to Neo4j.")

    extract_jobs.run_extraction("garo_2.pdf", pdf_path=tmp_path / "garo_2.pdf",
                                uploads_dir=tmp_path, runner=runner)

    assert during["state"]["decision"] == "extracting"


def _inline(work):
    """A spawn that runs the job on this thread, so tests stay deterministic."""
    work()


def test_begin_runs_the_extraction_and_reports_that_it_started(tmp_path):
    def runner(cmd, **kwargs):
        return _FakeCompleted(stdout="Uploaded 7 triples to Neo4j.")

    started = extract_jobs.begin("garo_2.pdf", pdf_path=tmp_path / "garo_2.pdf",
                                 uploads_dir=tmp_path, runner=runner, spawn=_inline)

    assert started is True
    assert extract_jobs.state_for("garo_2.pdf", uploads_dir=tmp_path)["triples_loaded"] == 7


def test_a_second_extraction_is_refused_while_one_is_running(tmp_path):
    """Two 72-minute jobs against one CPU-only Ollama is worse than a queue.
    The second caller is told no rather than silently making both crawl."""
    outcome = {}

    def runner(cmd, **kwargs):
        outcome["second"] = extract_jobs.begin(
            "other.pdf", pdf_path=tmp_path / "other.pdf",
            uploads_dir=tmp_path, runner=runner, spawn=_inline)
        return _FakeCompleted(stdout="Uploaded 1 triples to Neo4j.")

    extract_jobs.begin("garo_2.pdf", pdf_path=tmp_path / "garo_2.pdf",
                       uploads_dir=tmp_path, runner=runner, spawn=_inline)

    assert outcome["second"] is False
    assert extract_jobs.state_for("other.pdf", uploads_dir=tmp_path) is None


def test_the_lock_is_released_so_the_next_paper_can_run(tmp_path):
    def runner(cmd, **kwargs):
        return _FakeCompleted(stdout="Uploaded 1 triples to Neo4j.")

    extract_jobs.begin("first.pdf", pdf_path=tmp_path / "first.pdf",
                       uploads_dir=tmp_path, runner=runner, spawn=_inline)

    assert extract_jobs.begin("second.pdf", pdf_path=tmp_path / "second.pdf",
                              uploads_dir=tmp_path, runner=runner,
                              spawn=_inline) is True


def test_the_lock_is_released_even_when_the_run_crashes(tmp_path):
    """A crash that kept the lock would block every later paper until restart."""
    def crashing(cmd, **kwargs):
        raise OSError("no such executable")

    extract_jobs.begin("first.pdf", pdf_path=tmp_path / "first.pdf",
                       uploads_dir=tmp_path, runner=crashing, spawn=_inline)

    def ok(cmd, **kwargs):
        return _FakeCompleted(stdout="Uploaded 1 triples to Neo4j.")

    assert extract_jobs.begin("second.pdf", pdf_path=tmp_path / "second.pdf",
                              uploads_dir=tmp_path, runner=ok,
                              spawn=_inline) is True


def test_the_run_output_is_kept_on_disk(tmp_path):
    """72 minutes of output is the only diagnostic when a run goes wrong."""
    def runner(cmd, **kwargs):
        return _FakeCompleted(stdout="chunk 1 of 9\nUploaded 2 triples to Neo4j.")

    extract_jobs.run_extraction("garo_2.pdf", pdf_path=tmp_path / "garo_2.pdf",
                                uploads_dir=tmp_path, runner=runner)

    log = (tmp_path / "logs" / "garo_2.pdf.log").read_text(encoding="utf-8")
    assert "chunk 1 of 9" in log
