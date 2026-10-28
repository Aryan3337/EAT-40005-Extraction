"""Tests for neo4j_loader/rollback.py -- undoing one load.

WHY THIS EXISTS: tests/test_insert.py's own docstring names the gap --
"without a run id on the relationship there is no way ... to roll back a
bad load". add_triples has stamped every relationship with a shared run_id
since 2026-10-05 precisely so a load is addressable as a unit, and nothing
ever used it. Until something does, every extraction into the production
graph is a one-way write.

This matters more now that approving a paper in the admin UI starts an
extraction. A reviewer can approve in one click; they need the same
confidence that a bad load can come back out.

WHAT THESE DO NOT COVER: Cypher semantics, for the same reason as
test_insert.py -- there is no Neo4j in the unit suite. These assert on the
query and parameters handed to the driver.
"""

import pytest

from neo4j_loader.rollback import delete_run


class FakeResult:
    def __init__(self, record):
        self._record = record

    def single(self):
        return self._record


class FakeSession:
    """Answers each query with a canned count and records what it was asked."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        return FakeResult(self.answers.pop(0) if self.answers else {})


class FakeDriver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


def test_it_reports_how_many_relationships_a_run_loaded():
    session = FakeSession([{"c": 37}])
    driver = FakeDriver(session)

    result = delete_run("20261005T021421Z-cab24022", driver=driver,
                        dry_run=True)

    assert result["relationships"] == 37


def test_a_dry_run_deletes_nothing():
    """The first thing anyone does with a delete tool is check what it would
    hit. That must not be the same keystroke as doing it."""
    session = FakeSession([{"c": 37}])
    driver = FakeDriver(session)

    delete_run("some-run", driver=driver, dry_run=True)

    queries = " ".join(query for query, _ in session.calls)
    assert "DELETE" not in queries.upper()


def test_it_deletes_only_the_relationships_of_that_run():
    session = FakeSession([{"c": 12}, {"ids": ["n:1"]}, {"c": 12}, {"c": 3}])
    driver = FakeDriver(session)

    delete_run("doomed-run", driver=driver)

    delete_calls = [
        (query, params)
        for query, params in session.calls
        if "DELETE" in query.upper()
    ]
    assert delete_calls, "nothing was deleted"
    query, params = delete_calls[0]
    assert params["run_id"] == "doomed-run"
    # Scoped by run_id, or it would empty the graph.
    assert "run_id" in query


def test_it_clears_up_nodes_the_delete_left_stranded():
    """insert_triple MERGEs nodes, so deleting a run's relationships can
    leave entities with nothing attached. Those are invisible to retrieval
    but still counted, and they accumulate."""
    session = FakeSession([{"c": 12}, {"ids": ["n:1"]}, {"c": 12}, {"c": 5}])
    driver = FakeDriver(session)

    result = delete_run("doomed-run", driver=driver)

    assert result["orphan_nodes"] == 5
    queries = " ".join(query for query, _ in session.calls)
    assert "degree" in queries.lower() or "NOT (n)--()" in queries


def test_an_empty_run_id_is_refused():
    """A blank id must never become 'match everything'."""
    with pytest.raises(ValueError):
        delete_run("", driver=FakeDriver(FakeSession([])))


def test_a_run_that_loaded_nothing_deletes_nothing():
    session = FakeSession([{"c": 0}])
    driver = FakeDriver(session)

    result = delete_run("never-ran", driver=driver)

    assert result["relationships"] == 0
    queries = " ".join(query for query, _ in session.calls)
    assert "DELETE" not in queries.upper()


def test_the_orphan_sweep_only_touches_nodes_this_run_attached_to():
    """A rollback must not delete nodes it did not strand.

    The first version swept every node in the graph with no relationships,
    so undoing a 1-triple run on 2026-10-28 also removed 22 unrelated
    pre-existing orphans. Harmless that time -- a node with no
    relationships is invisible to retrieval -- but a delete tool that
    reaches beyond its stated scope is not one anybody should trust
    against a production graph.
    """
    session = FakeSession([
        {"c": 1},                       # count
        {"ids": ["n:1", "n:2"]},        # endpoints of this run
        {"c": 1},                       # delete
        {"c": 2},                       # orphan cleanup
    ])
    driver = FakeDriver(session)

    delete_run("scoped-run", driver=driver)

    orphan_calls = [
        (query, params) for query, params in session.calls
        if "NOT (n)--()" in query
    ]
    assert orphan_calls, "no orphan cleanup ran"
    query, params = orphan_calls[0]
    # Scoped by the endpoints collected before the delete, not the whole graph.
    assert "elementId(n) IN" in query
    assert params.get("ids") == ["n:1", "n:2"]
