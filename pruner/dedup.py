"""
Tier 2 -- near-duplicate entity detection and merging.

Compares newly-arrived nodes against the *whole graph* (not just within
the new batch) grouped by label, because a duplicate of "Jabba" might
already exist from an earlier extraction run. Two similarity bands:

  >= DEDUP_AUTO_MERGE_THRESHOLD  -> merge automatically (archived first)
  >= DEDUP_REVIEW_THRESHOLD      -> flag for human review, don't merge

Requires `rapidfuzz` for fuzzy matching; falls back to Python's built-in
difflib if it isn't installed (slower, slightly less accurate, but no
extra dependency).

Note (verified 2026-09-09): the real pipeline labels every node just
`:Entity`, not one of config.ENTITY_CATEGORIES -- see the comment there.
_fetch_nodes_by_label() below falls back to the node's own label when
nothing in ENTITY_CATEGORIES matches, so against the real graph every
node lands in one "Entity" bucket. Still correct, just means Tier 2
compares everything to everything rather than getting a category-scoped
speedup.
"""

import re
from collections import defaultdict

from . import audit, config, rules

try:
    from rapidfuzz import fuzz

    def _similarity(a: str, b: str) -> float:
        return fuzz.ratio(a, b)
except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    def _similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _fetch_nodes_by_label(conn):
    cypher = f"""
    MATCH (n)
    WHERE n.name IS NOT NULL AND NOT coalesce(n.{config.REVIEW_FLAG_PROPERTY}, false)
    RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props
    """
    rows = conn.run(cypher)
    grouped = defaultdict(list)
    for row in rows:
        label = next(iter(set(row["labels"]) & config.KNOWN_LABELS), None) or (row["labels"][0] if row["labels"] else "")
        grouped[label].append(row)
    return grouped


def merge_nodes(conn, keep_id, absorb_id, batch_id, dry_run=False):
    """Redirects all relationships from `absorb_id` onto `keep_id`, records
    the absorbed node's name as an alias on the survivor, then deletes the
    absorbed node. Archived first -- see pruner.audit."""
    absorb_row = conn.run(
        "MATCH (n) WHERE elementId(n) = $id RETURN labels(n) AS labels, properties(n) AS props",
        id=absorb_id,
    )
    element = absorb_row[0] if absorb_row else {}
    audit.log_removal({
        "action": "merge", "tier": 2, "target": "node",
        "reason": "near_duplicate", "batch_id": batch_id,
        "kept_id": keep_id, "element": element,
    })
    if dry_run:
        return
    conn.run(
        """
        MATCH (keep) WHERE elementId(keep) = $keep_id
        MATCH (absorb) WHERE elementId(absorb) = $absorb_id
        SET keep.aliases = coalesce(keep.aliases, []) + [absorb.name]
        """,
        keep_id=keep_id, absorb_id=absorb_id,
    )
    # Neo4j can't parameterize relationship types, so redirect per-type.
    rel_types = conn.run(
        "MATCH (a)-[r]->() WHERE elementId(a) = $id RETURN DISTINCT type(r) AS t",
        id=absorb_id,
    ) + conn.run(
        "MATCH ()-[r]->(a) WHERE elementId(a) = $id RETURN DISTINCT type(r) AS t",
        id=absorb_id,
    )
    for row in {r["t"] for r in rel_types}:
        conn.run(
            f"""
            MATCH (absorb) WHERE elementId(absorb) = $absorb_id
            MATCH (keep) WHERE elementId(keep) = $keep_id
            OPTIONAL MATCH (absorb)-[r:`{row}`]->(other)
            FOREACH (_ IN CASE WHEN other IS NOT NULL THEN [1] ELSE [] END |
                MERGE (keep)-[:`{row}`]->(other)
            )
            WITH absorb, keep
            OPTIONAL MATCH (other2)-[r2:`{row}`]->(absorb)
            FOREACH (_ IN CASE WHEN other2 IS NOT NULL THEN [1] ELSE [] END |
                MERGE (other2)-[:`{row}`]->(keep)
            )
            """,
            absorb_id=absorb_id, keep_id=keep_id,
        )
    conn.run("MATCH (n) WHERE elementId(n) = $id DETACH DELETE n", id=absorb_id)


def run_tier2(conn, batch_id=None, dry_run=False):
    """Compares all same-labelled nodes pairwise (within each label group)
    for near-duplicate names. Auto-merges high-confidence matches, flags
    the rest for review. batch_id is recorded in the audit log but the
    comparison itself runs against the whole graph, since a duplicate of
    a new node may be an older node from a previous batch."""
    summary = {"merged": 0, "flagged": 0}
    grouped = _fetch_nodes_by_label(conn)

    for label, nodes in grouped.items():
        seen = []  # (normalized_name, node_row)
        for node in nodes:
            name = str(node["props"].get("name", ""))
            norm = _normalize(name)
            merged_into_existing = False
            for existing_norm, existing_node in seen:
                if norm == existing_norm:
                    # identical after normalization -> certain duplicate
                    merge_nodes(conn, existing_node["id"], node["id"], batch_id, dry_run)
                    summary["merged"] += 1
                    merged_into_existing = True
                    break
                score = _similarity(norm, existing_norm)
                if score >= config.DEDUP_AUTO_MERGE_THRESHOLD:
                    merge_nodes(conn, existing_node["id"], node["id"], batch_id, dry_run)
                    summary["merged"] += 1
                    merged_into_existing = True
                    break
                if score >= config.DEDUP_REVIEW_THRESHOLD:
                    reason = f"possible_duplicate_of:{existing_node['props'].get('name')}"
                    rules.flag_node(conn, node["id"], reason, dry_run)
                    summary["flagged"] += 1
            if not merged_into_existing:
                seen.append((norm, node))

    return summary
