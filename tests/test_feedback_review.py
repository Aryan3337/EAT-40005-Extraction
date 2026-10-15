"""Feedback loop backend: triple-id linking, per-item delete, admin review,
archive semantics and stats -- exercised against a fake Neo4j driver so the
logic is checked without a live database."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth_store as auth_store_module
from auth_store import AuthStore


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def single(self):
        return self._rows[0] if self._rows else None

    def consume(self):
        return None

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self.driver.calls.append((query, params))
        queued = self.driver.results.pop(0) if self.driver.results else []
        return FakeResult(queued)


class FakeDriver:
    def __init__(self):
        self.calls = []
        self.results = []

    def session(self):
        return FakeSession(self)

    def close(self):
        pass


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(auth_store_module, "URI", "neo4j://localhost")
    monkeypatch.setattr(auth_store_module, "USERNAME", "u")
    monkeypatch.setattr(auth_store_module, "PASSWORD", "p")
    driver = FakeDriver()
    monkeypatch.setattr(
        auth_store_module.GraphDatabase, "driver", lambda *a, **k: driver
    )
    instance = AuthStore()
    driver.calls.clear()
    return instance, driver


def test_save_feedback_stores_cleaned_triple_ids_and_pending_status(store):
    instance, driver = store
    instance.save_feedback(
        "a@b.c", "conv1", "answer", "notHelpful", "wrong",
        triple_ids=["4:x:1", "  ", None, "4:x:2"],
    )
    query, params = driver.calls[-1]
    assert params["triple_ids"] == ["4:x:1", "4:x:2"]
    assert "status: 'pending'" in query


def test_save_feedback_without_ids_still_works(store):
    instance, driver = store
    instance.save_feedback("a@b.c", "conv1", "answer", "helpful", "")
    assert driver.calls[-1][1]["triple_ids"] == []


def test_delete_feedback_item_is_scoped_to_owner_and_reports_missing(store):
    instance, driver = store
    driver.results = [[{"deleted": 0}]]
    with pytest.raises(ValueError):
        instance.delete_feedback_item("a@b.c", "fb1")
    query, params = driver.calls[-1]
    assert params == {"email": "a@b.c", "id": "fb1"}
    assert "User {email: $email}" in query


def test_delete_feedback_item_requires_id(store):
    instance, _ = store
    with pytest.raises(ValueError):
        instance.delete_feedback_item("a@b.c", "")


def test_review_rejected_never_archives_even_if_asked(store):
    instance, driver = store
    driver.results = [[{"triple_ids": ["4:x:1"]}]]
    instance.review_feedback(
        "fb1", admin_email="adm@x.y", action="rejected", note="fine as is",
        archive_triples=True,
    )
    assert len(driver.calls) == 1  # only the Feedback update, no archive query
    assert "r.archived" not in driver.calls[0][0]


def test_review_approved_with_archive_flags_graph_triples_only(store, capsys):
    instance, driver = store
    driver.results = [[{"triple_ids": ["4:x:1", "csv:3"]}]]
    instance.review_feedback(
        "fb1", admin_email="adm@x.y", action="approved", note="wrong fact",
        archive_triples=True,
    )
    archive_query, params = driver.calls[-1]
    assert "r.archived = true" in archive_query
    assert params["ids"] == ["4:x:1"]  # csv id filtered out
    assert params["admin_email"] == "adm@x.y"
    assert params["note"] == "wrong fact"
    assert "CSV-sourced" in capsys.readouterr().out


def test_review_approved_without_archive_flag_leaves_graph_alone(store):
    instance, driver = store
    driver.results = [[{"triple_ids": ["4:x:1"]}]]
    instance.review_feedback("fb1", admin_email="a", action="approved")
    assert len(driver.calls) == 1


def test_review_records_provenance_fields(store):
    instance, driver = store
    driver.results = [[{"triple_ids": []}]]
    instance.review_feedback("fb1", admin_email="adm@x.y", action="approved", note="n")
    query, params = driver.calls[0]
    for field in ("reviewed_by", "reviewed_at", "review_note", "review_action"):
        assert f"f.{field}" in query
    assert params["admin_email"] == "adm@x.y"


def test_review_validates_input_and_missing_feedback(store):
    instance, driver = store
    with pytest.raises(ValueError):
        instance.review_feedback("fb1", admin_email="a", action="maybe")
    with pytest.raises(ValueError):
        instance.review_feedback("fb1", admin_email="a", action="approved", note="x" * 2001)
    with pytest.raises(ValueError):
        instance.review_feedback("", admin_email="a", action="approved")
    driver.results = [[]]  # feedback id not found
    with pytest.raises(ValueError):
        instance.review_feedback("nope", admin_email="a", action="approved")


def test_all_feedback_resolves_triples_in_one_batched_lookup(store):
    instance, driver = store
    driver.results = [
        [
            {"user_email": "u1", "id": "f1", "triple_ids": ["t1", "t2"]},
            {"user_email": "u2", "id": "f2", "triple_ids": ["t2", "csv:0"]},
        ],
        [
            {"id": "t1", "subject": "A", "predicate": "P", "object": "B", "archived": False},
            {"id": "t2", "subject": "C", "predicate": "Q", "object": "D", "archived": True},
        ],
    ]
    rows = instance.all_feedback("pending")
    assert len(driver.calls) == 2  # not one lookup per row
    assert driver.calls[1][1]["ids"] == ["t1", "t2"]  # csv id excluded, deduped
    assert [t["id"] for t in rows[0]["triples"]] == ["t1", "t2"]
    assert [t["id"] for t in rows[1]["triples"]] == ["t2"]
    assert rows[1]["triples"][0]["archived"] is True


def test_feedback_stats_shape(store):
    instance, driver = store
    driver.results = [
        [{"total": 5, "helpful": 2, "not_helpful": 3, "pending": 4,
          "approved": 1, "dismissed": 0}],
        [{"archived_triples": 1}],
    ]
    stats = instance.feedback_stats()
    assert stats == {
        "total": 5, "helpful": 2, "not_helpful": 3, "pending": 4,
        "approved": 1, "dismissed": 0, "archived_triples": 1,
    }


def test_correction_replaces_triple_and_archives_old_one(store):
    instance, driver = store
    driver.results = [[{"triple_ids": ["t1"]}], [{"created": 1}]]
    instance.review_feedback(
        "f1", admin_email="a@x.com", action="approved", note="wrong object",
        correction={"triple_id": "t1", "subject": "Garo", "predicate": "LIVE_IN",
                    "object": "Meghalaya"},
    )
    query, params = driver.calls[-1]
    assert "CREATE (s)-[n:`LIVE_IN`]->(o)" in query
    assert "old.archived = true" in query
    assert "DELETE" not in query
    assert params["id"] == "t1" and params["object"] == "Meghalaya"


def test_correction_validation(store):
    instance, driver = store
    bad = {"triple_id": "t1", "subject": "A", "predicate": "X`) DETACH DELETE n //",
           "object": "B"}
    with pytest.raises(ValueError):
        instance.review_feedback("f1", admin_email="a", action="approved", correction=bad)
    with pytest.raises(ValueError):
        instance.review_feedback(
            "f1", admin_email="a", action="rejected",
            correction={"triple_id": "t1", "subject": "A", "predicate": "P", "object": "B"})
    with pytest.raises(ValueError):
        instance.review_feedback(
            "f1", admin_email="a", action="approved",
            correction={"triple_id": "csv:1", "subject": "A", "predicate": "P", "object": "B"})
    assert driver.calls == []


def test_correction_must_target_a_triple_from_that_feedback(store):
    instance, driver = store
    driver.results = [[{"triple_ids": ["t1"]}]]
    with pytest.raises(ValueError):
        instance.review_feedback(
            "f1", admin_email="a", action="approved",
            correction={"triple_id": "other", "subject": "A", "predicate": "P", "object": "B"})


def test_pruner_approve_records_provenance_and_reject_archives(monkeypatch):
    from pruner import review

    class Conn:
        def __init__(self):
            self.calls = []

        def run(self, q, **p):
            self.calls.append((q, p))
            return [{"props": {"name": "x"}}]

    c = Conn()
    review.approve(c, "e1", "relationship", approved_by="a@x.com", reason="ok")
    q, p = c.calls[-1]
    assert "approved_at" in q and p["approved_by"] == "a@x.com"

    c = Conn()
    import pruner.audit as audit
    monkeypatch.setattr(audit, "log_removal", lambda record, *a, **k: None)
    review.reject(c, "e1", "node", rejected_by="a@x.com", reason="noise")
    q, p = c.calls[-1]
    assert "archived = true" in q and "DELETE" not in q
