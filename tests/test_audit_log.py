"""ADM-2/3/4: structured audit log, reviewer identity, operator identity."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import audit_log


def test_events_are_appended_and_read_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "a.jsonl"))
    audit_log.log_event("auth.login", actor="a@x.com", ip="1.2.3.4")
    audit_log.log_event("auth.login", actor="b@x.com", outcome="failure")
    rows = audit_log.read_events()
    assert [r["actor"] for r in rows] == ["b@x.com", "a@x.com"]
    assert rows[1]["ip"] == "1.2.3.4" and "at" in rows[1]
    assert audit_log.read_events(outcome="failure")[0]["actor"] == "b@x.com"
    assert len(audit_log.read_events(event_type="auth")) == 2
    assert audit_log.read_events(event_type="graph") == []


def test_secrets_are_never_written(tmp_path, monkeypatch):
    path = tmp_path / "a.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(path))
    audit_log.log_event("auth.login", actor="a", password="hunter2",
                        session_token="t", admin_secret="s", note="ok")
    text = path.read_text()
    assert "hunter2" not in text and "admin_secret" not in text
    assert json.loads(text)["note"] == "ok"


def test_logging_failure_never_raises(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(blocker / "sub" / "a.jsonl"))
    audit_log.log_event("auth.login", actor="a")  # must not raise


def test_bad_lines_are_skipped_and_recent_errors_filter(tmp_path, monkeypatch):
    path = tmp_path / "a.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(path))
    audit_log.log_event("auth.login", actor="ok")
    with open(path, "a") as f:
        f.write("not json\n")
    audit_log.log_event("system.error", outcome="error", where="auth")
    audit_log.log_event("auth.login", actor="x", outcome="failure")
    errors = audit_log.recent_errors()
    assert [e["type"] for e in errors] == ["auth.login", "system.error"]


def test_operator_prefers_env(monkeypatch):
    monkeypatch.setenv("OPERATOR", "jane")
    assert audit_log.current_operator() == "jane"
    monkeypatch.delenv("OPERATOR")
    assert audit_log.current_operator()


def test_pruner_removals_carry_operator(tmp_path, monkeypatch):
    from pruner import audit
    monkeypatch.setenv("OPERATOR", "jane")
    log = tmp_path / "p.jsonl"
    audit.log_removal({"action": "delete", "element": {}}, str(log))
    audit.log_removal({"action": "archive", "operator": "bob"}, str(log))
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert [r["operator"] for r in rows] == ["jane", "bob"]


def test_manual_review_records_reviewer(tmp_path):
    import admin_ingest
    from admin_ingest import IngestDecision, IngestOutcome, _append_to_queue
    outcome = IngestOutcome(decision=IngestDecision.READY_TO_EXTRACT,
                            paper="p.pdf", outcome="MANUAL_APPROVED",
                            reasons=[], stored_path="x")
    _append_to_queue(tmp_path, outcome, by="manual_review", reviewer="a@x.com")
    row = json.loads((tmp_path / "queue.jsonl").read_text().splitlines()[0])
    assert row["by"] == "manual_review" and row["reviewer"] == "a@x.com"
