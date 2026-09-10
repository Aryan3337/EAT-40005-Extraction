"""
Tier 1 -- structural/schema checks.

These are the checks that don't need any judgement call: if a triple
fails one of these, it's noise by your own project's rules (mainly KG8's
"no entry without a source"), so it's safe to auto-delete. Every removal
is archived first via pruner.audit.log_removal.

Note: malformed extractions (e.g. UNKNOWN-labelled entities) are already
filtered out before anything reaches Neo4j in the current pipeline, so
there's no "unknown label" check here -- nothing to catch on the DB side.

Also included: a heuristic flag (not delete) for entity names that look
like mis-split sentence fragments rather than real entities -- e.g. the
"for catching fish" ACT node from your extraction paper's own example.
That one is judgement-call territory, so it goes to the review queue
(Tier 1.5) instead of being deleted outright.

--- Verified against the actual pipeline on 2026-09-09 ---
neo4j_loader/insert.py sets config.SOURCE_PROPERTY (source_file) on every
RELATIONSHIP it creates, but never on nodes -- MERGE (s:Entity {name:
$subject}) sets no source property at all. That means
find_missing_source_nodes() would match literally every node in the
graph, and run_tier1() would DETACH DELETE all of them (which also wipes
every relationship attached to them, well beyond anything actually
noisy). find_missing_source_nodes() is left defined below in case
node-level source tracking gets added to insert.py later, but it is NOT
called from run_tier1() -- see the commented-out line there. The
relationship-level check (find_missing_source_rels) is unaffected and
still runs normally, since relationships genuinely do carry source_file.
"""

from . import audit, config


def find_missing_source_nodes(conn, batch_id=None):
    """NOT called by run_tier1() against the current pipeline -- see the
    module docstring. Kept here, unused, in case node-level source
    tracking is added to insert.py later (at which point re-add the call
    in run_tier1() below)."""
    where_batch = f"AND n.{config.BATCH_PROPERTY} = $batch_id" if batch_id is not None else ""
    cypher = f"""
    MATCH (n)
    WHERE (n.{config.SOURCE_PROPERTY} IS NULL OR n.{config.SOURCE_PROPERTY} = '')
    {where_batch}
    RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props
    """
    return conn.run(cypher, batch_id=batch_id)


def find_missing_source_rels(conn, batch_id=None):
    where_batch = f"AND r.{config.BATCH_PROPERTY} = $batch_id" if batch_id is not None else ""
    cypher = f"""
    MATCH (a)-[r]->(b)
    WHERE (r.{config.SOURCE_PROPERTY} IS NULL OR r.{config.SOURCE_PROPERTY} = '')
    {where_batch}
    RETURN elementId(r) AS id, type(r) AS type, properties(r) AS props,
           elementId(a) AS start_id, elementId(b) AS end_id
    """
    return conn.run(cypher, batch_id=batch_id)


def find_self_loop_rels(conn, batch_id=None):
    where_batch = f"AND r.{config.BATCH_PROPERTY} = $batch_id" if batch_id is not None else ""
    cypher = f"""
    MATCH (a)-[r]->(b)
    WHERE elementId(a) = elementId(b)
    {where_batch}
    RETURN elementId(r) AS id, type(r) AS type, properties(r) AS props,
           elementId(a) AS start_id
    """
    return conn.run(cypher, batch_id=batch_id)


def find_duplicate_relationships(conn, batch_id=None):
    """Exact duplicates: same start node, end node, and relationship type.
    Keeps the relationship with the lower elementId (assumed = created
    first), flags the rest for deletion."""
    where_batch = f"AND r2.{config.BATCH_PROPERTY} = $batch_id" if batch_id is not None else ""
    cypher = f"""
    MATCH (a)-[r1]->(b)
    MATCH (a)-[r2]->(b)
    WHERE type(r1) = type(r2) AND elementId(r1) < elementId(r2)
    {where_batch}
    RETURN elementId(r2) AS id, type(r2) AS type, properties(r2) AS props,
           elementId(a) AS start_id, elementId(b) AS end_id
    """
    return conn.run(cypher, batch_id=batch_id)


def find_oversized_entity_nodes(conn, batch_id=None):
    """Heuristic, not a hard rule: entity names with more words than
    config.MAX_SENSIBLE_ENTITY_WORDS usually mean the extraction step
    grabbed a sentence fragment instead of an entity. Flag for review,
    don't auto-delete -- could occasionally be a legitimate long name."""
    where_batch = f"AND n.{config.BATCH_PROPERTY} = $batch_id" if batch_id is not None else ""
    cypher = f"""
    MATCH (n)
    WHERE NOT coalesce(n.{config.REVIEW_FLAG_PROPERTY}, false) AND n.name IS NOT NULL
    {where_batch}
    RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props
    """
    rows = conn.run(cypher, batch_id=batch_id)
    flagged = []
    for row in rows:
        name = str(row["props"].get("name", ""))
        if len(name.split()) > config.MAX_SENSIBLE_ENTITY_WORDS:
            flagged.append(row)
    return flagged


def delete_node(conn, node_id, reason, batch_id, dry_run=False, log_path=None):
    row = conn.run(
        "MATCH (n) WHERE elementId(n) = $id RETURN labels(n) AS labels, properties(n) AS props",
        id=node_id,
    )
    element = row[0] if row else {}
    record = {"action": "delete", "tier": 1, "target": "node", "reason": reason,
              "batch_id": batch_id, "element": element}
    audit.log_removal(record, log_path) if log_path else audit.log_removal(record)
    if not dry_run:
        conn.run("MATCH (n) WHERE elementId(n) = $id DETACH DELETE n", id=node_id)


def delete_relationship(conn, rel_id, reason, batch_id, dry_run=False, log_path=None):
    row = conn.run(
        "MATCH ()-[r]->() WHERE elementId(r) = $id RETURN type(r) AS type, properties(r) AS props",
        id=rel_id,
    )
    element = row[0] if row else {}
    record = {"action": "delete", "tier": 1, "target": "relationship", "reason": reason,
              "batch_id": batch_id, "element": element}
    audit.log_removal(record, log_path) if log_path else audit.log_removal(record)
    if not dry_run:
        conn.run("MATCH ()-[r]->() WHERE elementId(r) = $id DELETE r", id=rel_id)


def flag_node(conn, node_id, reason, dry_run=False):
    if dry_run:
        return
    conn.run(
        f"""
        MATCH (n) WHERE elementId(n) = $id
        SET n.{config.REVIEW_FLAG_PROPERTY} = true,
            n.{config.REVIEW_REASON_PROPERTY} = $reason,
            n.{config.REVIEW_FLAGGED_AT_PROPERTY} = datetime()
        """,
        id=node_id, reason=reason,
    )


def flag_relationship(conn, rel_id, reason, dry_run=False, extra_props=None):
    if dry_run:
        return
    extra_props = extra_props or {}
    set_clauses = ", ".join(f"r.{k} = ${k}" for k in extra_props)
    set_clause_str = f", {set_clauses}" if set_clauses else ""
    conn.run(
        f"""
        MATCH ()-[r]->() WHERE elementId(r) = $id
        SET r.{config.REVIEW_FLAG_PROPERTY} = true,
            r.{config.REVIEW_REASON_PROPERTY} = $reason,
            r.{config.REVIEW_FLAGGED_AT_PROPERTY} = datetime()
            {set_clause_str}
        """,
        id=rel_id, reason=reason, **extra_props,
    )


def run_tier1(conn, batch_id=None, dry_run=False):
    """Runs every Tier 1 check and returns a summary dict. Hard-noise
    matches are deleted (archived first); the oversized-entity heuristic
    is only flagged, never deleted.

    Node-level missing-source deletion is intentionally NOT run here --
    see the module docstring and find_missing_source_nodes() above."""
    summary = {"deleted_nodes": 0, "deleted_rels": 0, "flagged_nodes": 0}

    # for row in find_missing_source_nodes(conn, batch_id):
    #     delete_node(conn, row["id"], "missing_source", batch_id, dry_run)
    #     summary["deleted_nodes"] += 1
    # ^ disabled: every node in the current schema is "missing" a source
    # property by design (only relationships carry source_file), so this
    # would delete the entire graph. Re-enable only after insert.py is
    # changed to set a source property on nodes too.

    for row in find_missing_source_rels(conn, batch_id):
        delete_relationship(conn, row["id"], "missing_source", batch_id, dry_run)
        summary["deleted_rels"] += 1

    for row in find_self_loop_rels(conn, batch_id):
        delete_relationship(conn, row["id"], "self_loop", batch_id, dry_run)
        summary["deleted_rels"] += 1

    for row in find_duplicate_relationships(conn, batch_id):
        delete_relationship(conn, row["id"], "exact_duplicate", batch_id, dry_run)
        summary["deleted_rels"] += 1

    for row in find_oversized_entity_nodes(conn, batch_id):
        flag_node(conn, row["id"], "oversized_entity_name", dry_run)
        summary["flagged_nodes"] += 1

    return summary
