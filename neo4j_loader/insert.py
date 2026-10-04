import uuid
from datetime import datetime, timezone

from neo4j_loader.connection import get_driver
from neo4j_loader.cleaner import clean_relation


def new_run_id() -> str:
    """A run id that an operator can read.

    MERGE never deletes, so every load piles on top of the last one. The run
    id is what makes a load identifiable from inside Neo4j afterwards -- to
    find what a given load produced, to roll one back, or to find triples an
    earlier run created that a later run stopped producing (those keep
    serving the chatbot otherwise).

    Leads with a UTC timestamp rather than being a bare uuid so that run ids
    sort chronologically and are legible in the Neo4j browser -- an operator
    scanning them can tell Monday's load from Thursday's. The short random
    suffix keeps two loads in the same second distinct.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def insert_triple(tx, triple, run_id, ingested_at):
    subject = triple["subject"]
    relation = clean_relation(triple.get("predicate", triple.get("relation", "RELATED_TO")))
    obj = triple["object"]

    # first_ingested_at is ON CREATE only: re-loading a triple must not
    # rewrite when it first entered the graph, or "new in this load" and
    # "confirmed again by this load" become indistinguishable. run_id and
    # ingested_at are set unconditionally and so always name the most recent
    # load that produced this triple -- which is what makes
    #   MATCH ()-[r]->() WHERE r.run_id <> $current
    # a usable stale-triple query.
    query = f"""
    MERGE (s:Entity {{name: $subject}})
    MERGE (o:Entity {{name: $object}})
    MERGE (s)-[r:{relation}]->(o)
    ON CREATE SET r.first_ingested_at = $ingested_at
    SET r.source_file = $source_file,
        r.source_section = $source_section,
        r.confidence = $confidence,
        r.passage = $passage,
        r.sentence_ref = $sentence_ref,
        r.run_id = $run_id,
        r.ingested_at = $ingested_at
    """

    tx.run(
        query,
        subject=subject,
        object=obj,
        source_file=triple.get("source_file", ""),
        source_section=triple.get("source_section", ""),
        confidence=triple.get("confidence", ""),
        passage=triple.get("passage", ""),
        sentence_ref=triple.get("sentence_ref", ""),
        run_id=run_id,
        ingested_at=ingested_at,
    )


def add_triples(triples, run_id=None, driver=None):
    """Load triples, stamping every one with the same run id and timestamp.

    One call is one run: a per-triple id would make "everything from this
    load" unqueryable, which is the only reason the field exists. Returns
    (inserted, skipped, run_id) -- the caller is expected to record the run
    id, since a run id nobody wrote down is no better than not having one.

    `driver` is injectable so the loader can be tested without a live
    database; it defaults to the project's configured driver.
    """
    run_id = run_id or new_run_id()
    ingested_at = datetime.now(timezone.utc).isoformat()
    driver = driver if driver is not None else get_driver()

    inserted = 0
    skipped = 0

    with driver.session() as session:
        for triple in triples:
            if triple["subject"] != "UNKNOWN":
                session.execute_write(insert_triple, triple, run_id, ingested_at)
                inserted += 1
            else:
                skipped += 1

    if inserted > 0:
        print(f"Uploaded {inserted} triples to Neo4j.")
        print(f"  run_id={run_id}  ingested_at={ingested_at}")
    else:
        print("No triples uploaded to Neo4j — all candidates were UNKNOWN or invalid.")

    if skipped > 0:
        print(f"Skipped {skipped} UNKNOWN/invalid triples.")

    return inserted, skipped, run_id
