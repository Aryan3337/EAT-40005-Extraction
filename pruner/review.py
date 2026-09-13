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


def approve(conn, element_id, kind="node"):
    """Human confirms the flagged item is actually fine -- clears the flag,
    leaves the data in place."""
    match_clause = "(n)" if kind == "node" else "()-[n]->()"
    conn.run(
        f"""
        MATCH {match_clause} WHERE elementId(n) = $id
        REMOVE n.{config.REVIEW_FLAG_PROPERTY}, n.{config.REVIEW_REASON_PROPERTY}, n.{config.REVIEW_FLAGGED_AT_PROPERTY}
        """,
        id=element_id,
    )


def reject(conn, element_id, kind="node"):
    """Human confirms it IS noise -- archive then delete, same as an
    automatic Tier 1/3 deletion."""
    match_clause = "(n)" if kind == "node" else "()-[n]->()"
    row = conn.run(
        f"MATCH {match_clause} WHERE elementId(n) = $id RETURN properties(n) AS props",
        id=element_id,
    )
    element = row[0]["props"] if row else {}
    audit.log_removal({
        "action": "delete", "tier": "human_review", "target": kind,
        "reason": "human_rejected", "element": element,
    })
    delete_clause = "MATCH (n) WHERE elementId(n) = $id DETACH DELETE n" if kind == "node" \
        else "MATCH ()-[n]->() WHERE elementId(n) = $id DELETE n"
    conn.run(delete_clause, id=element_id)
