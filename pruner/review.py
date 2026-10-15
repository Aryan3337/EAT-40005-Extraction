"""
The backend human-verification queue.

Anything Tier 1-3 wasn't confident enough about gets `needs_review = true`
plus a `review_reason` instead of being deleted. These functions are what
a review UI (or, for now, review_cli.py) calls to work through that queue.
"""

from . import audit, config


def list_flagged(conn, limit=100):
    cypher = f"""
    MATCH (n) WHERE n.{config.REVIEW_FLAG_PROPERTY} = true
    RETURN 'node' AS kind, elementId(n) AS id, labels(n) AS labels,
           properties(n) AS props
    UNION ALL
    MATCH ()-[r]->() WHERE r.{config.REVIEW_FLAG_PROPERTY} = true
    RETURN 'relationship' AS kind, elementId(r) AS id, [type(r)] AS labels,
           properties(r) AS props
    LIMIT $limit
    """
    return conn.run(cypher, limit=limit)


def approve(conn, element_id, kind="node", approved_by="", reason=""):
    """Human confirms the flagged item is actually fine -- clears the flag,
    leaves the data in place, and records who approved it, when and why."""
    match_clause = "(n)" if kind == "node" else "()-[n]->()"
    conn.run(
        f"""
        MATCH {match_clause} WHERE elementId(n) = $id
        REMOVE n.{config.REVIEW_FLAG_PROPERTY}, n.{config.REVIEW_REASON_PROPERTY}, n.{config.REVIEW_FLAGGED_AT_PROPERTY}
        SET n.approved_by = $approved_by, n.approved_at = datetime(),
            n.approval_reason = $reason
        """,
        id=element_id, approved_by=approved_by, reason=reason,
    )


def reject(conn, element_id, kind="node", rejected_by="", reason=""):
    """Human confirms it IS noise -- logged to the audit file, then ARCHIVED
    (flagged and excluded from retrieval) rather than deleted, so a wrong
    rejection can be undone by clearing `archived`."""
    match_clause = "(n)" if kind == "node" else "()-[n]->()"
    row = conn.run(
        f"MATCH {match_clause} WHERE elementId(n) = $id RETURN properties(n) AS props",
        id=element_id,
    )
    element = row[0]["props"] if row else {}
    audit.log_removal({
        "action": "archive", "tier": "human_review", "target": kind,
        "reason": reason or "human_rejected", "rejected_by": rejected_by,
        "element": element,
    })
    conn.run(
        f"""
        MATCH {match_clause} WHERE elementId(n) = $id
        REMOVE n.{config.REVIEW_FLAG_PROPERTY}
        SET n.archived = true, n.archived_at = datetime(),
            n.archived_by = $rejected_by, n.archive_reason = $reason
        """,
        id=element_id, rejected_by=rejected_by,
        reason=reason or "human_rejected",
    )
