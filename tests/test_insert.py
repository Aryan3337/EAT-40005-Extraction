"""Tests for neo4j_loader/insert.py -- run identity on loaded triples.

WHY THESE EXIST: insert_triple MERGEs and never deletes, so every load
accumulates on top of the last one. Without a run id on the relationship
there is no way, from inside Neo4j, to tell which load produced which
triple, to roll back a bad load, or to find triples a later run stopped
producing -- those just keep serving the chatbot. check_neo4j_recent.py
exists only to work around that absence by cross-referencing a local CSV.

WHAT THESE DO NOT COVER: Cypher semantics. These assert on the parameters
the driver is handed and on the presence of the ON CREATE clause, using a
fake transaction, because there is no Neo4j to run against in the unit
suite. That first_ingested_at really is preserved across a re-MERGE is a
claim only a live database can settle -- the end-to-end smoke check owns it.
"""

import re
from datetime import datetime

from neo4j_loader.insert import add_triples, insert_triple


class FakeTx:
    """Records what insert_triple would have sent to Neo4j."""

    def __init__(self):
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))


class FakeSession:
    def __init__(self, tx):
        self._tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute_write(self, fn, *args):
        return fn(self._tx, *args)


class FakeDriver:
    def __init__(self, tx):
        self._tx = tx

    def session(self):
        return FakeSession(self._tx)


def _triple(**overrides):
    triple = {
        "subject": "GaroPeople",
        "predicate": "BILINGUAL",
        "object": "Bengali",
        "source_file": "garo_1.pdf",
        "source_section": "Page 3",
        "confidence": "high",
        "passage": "(GaroPeople)-[BILINGUAL]->(Bengali)",
        "sentence_ref": "The majority of Garo people are bilingual.",
    }
    triple.update(overrides)
    return triple


# -- insert_triple -----------------------------------------------------------


def test_insert_triple_stamps_the_run_id_and_ingested_at():
    tx = FakeTx()
    insert_triple(tx, _triple(), run_id="run-abc", ingested_at="2026-10-04T18:00:00+00:00")

    _, params = tx.calls[0]
    assert params["run_id"] == "run-abc"
    assert params["ingested_at"] == "2026-10-04T18:00:00+00:00"


def test_insert_triple_sets_run_identity_on_the_relationship():
    tx = FakeTx()
    insert_triple(tx, _triple(), run_id="run-abc", ingested_at="2026-10-04T18:00:00+00:00")

    query, _ = tx.calls[0]
    assert "r.run_id = $run_id" in query
    assert "r.ingested_at = $ingested_at" in query


def test_first_ingested_at_is_only_written_when_the_relationship_is_created():
    # A re-load of the same triple must not rewrite when it first entered the
    # graph, or the distinction between "new tonight" and "confirmed again
    # tonight" is lost. ON CREATE SET is what preserves it.
    tx = FakeTx()
    insert_triple(tx, _triple(), run_id="r", ingested_at="t")

    query, _ = tx.calls[0]
    assert "ON CREATE SET r.first_ingested_at = $ingested_at" in query


def test_insert_triple_still_carries_the_provenance_fields_it_always_did():
    tx = FakeTx()
    insert_triple(tx, _triple(), run_id="r", ingested_at="t")

    _, params = tx.calls[0]
    assert params["subject"] == "GaroPeople"
    assert params["object"] == "Bengali"
    assert params["source_file"] == "garo_1.pdf"
    assert params["source_section"] == "Page 3"
    assert params["confidence"] == "high"
    assert params["sentence_ref"] == "The majority of Garo people are bilingual."


# -- add_triples -------------------------------------------------------------


def test_add_triples_generates_one_run_id_shared_by_every_triple_in_the_load():
    # One load is one run. Per-triple ids would make "everything from this
    # load" unqueryable, which is the whole point of having the field.
    tx = FakeTx()
    add_triples([_triple(), _triple(object="Garo")], driver=FakeDriver(tx))

    run_ids = {params["run_id"] for _, params in tx.calls}
    assert len(tx.calls) == 2
    assert len(run_ids) == 1
    assert next(iter(run_ids))


def test_add_triples_accepts_an_explicit_run_id():
    # The load script passes a meaningful id so a run in Neo4j can be tied
    # back to the CSV and the log line that produced it.
    tx = FakeTx()
    add_triples([_triple()], run_id="garo_1-2026-10-04", driver=FakeDriver(tx))

    _, params = tx.calls[0]
    assert params["run_id"] == "garo_1-2026-10-04"


def test_add_triples_stamps_a_utc_timestamp_that_parses():
    tx = FakeTx()
    add_triples([_triple()], driver=FakeDriver(tx))

    _, params = tx.calls[0]
    parsed = datetime.fromisoformat(params["ingested_at"])
    assert parsed.utcoffset() is not None, "ingested_at must be timezone-aware"
    assert parsed.utcoffset().total_seconds() == 0, "ingested_at must be UTC"


def test_add_triples_uses_the_same_timestamp_for_every_triple_in_the_load():
    tx = FakeTx()
    add_triples([_triple(), _triple(object="Garo"), _triple(object="Mandi")],
                driver=FakeDriver(tx))

    stamps = {params["ingested_at"] for _, params in tx.calls}
    assert len(stamps) == 1


def test_add_triples_reports_the_run_id_so_it_can_be_logged():
    # A run id nobody records is no better than no run id: the operator has
    # to be able to write it down next to the load they just did.
    tx = FakeTx()
    inserted, skipped, run_id = add_triples([_triple()], driver=FakeDriver(tx))

    assert (inserted, skipped) == (1, 0)
    assert run_id


def test_add_triples_still_skips_unknown_subjects():
    tx = FakeTx()
    inserted, skipped, _ = add_triples(
        [_triple(), _triple(subject="UNKNOWN")], driver=FakeDriver(tx)
    )

    assert (inserted, skipped) == (1, 1)
    assert len(tx.calls) == 1


def test_a_generated_run_id_is_traceable_to_when_it_ran():
    # Opaque uuids make a stale-triple query answerable but unreadable. A
    # generated id leads with the UTC date so an operator scanning run ids in
    # the browser can tell Monday's load from Thursday's.
    tx = FakeTx()
    add_triples([_triple()], driver=FakeDriver(tx))

    _, params = tx.calls[0]
    assert re.match(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$", params["run_id"]), params["run_id"]
