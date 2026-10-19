#!/usr/bin/env python3
"""ADM-5: plan the node-provenance migration. DRY RUN BY DEFAULT.

Today neo4j_loader/insert.py MERGEs every entity as (:Entity {name}) and
never records where it came from, so a node cannot be traced to a paper.
Provenance lives only on relationships (source_file / source_section).

What this script does:
  * default / --dry-run: READ-ONLY. Counts the entities that have no
    `source`, how many could be filled in from their relationships, how many
    sit in more than one paper, and prints the exact Cypher it would run.
  * --execute --approved-by <name>: runs ONLY the additive backfill (sets
    n.sources, n.source_backfilled_at/by on nodes that lack it). Nothing is
    deleted or relabelled. Refuses without --approved-by.

What it deliberately does NOT do: relabel entities (Person, Place, ...).
That needs a decision on the label scheme and a classification step, so it
is left in docs/ADM-5-migration-plan.md for approval before any code runs
against the live graph.
"""

import argparse
import json
import sys
from pathlib import Path

# Run as `python scripts/plan_node_migration.py`, Python only puts scripts/ on
# the import path -- add the repo root so `pruner` and `audit_log` resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BACKFILL = """
MATCH (n:Entity)
WHERE n.sources IS NULL
OPTIONAL MATCH (n)-[r]-()
WITH n, [s IN collect(DISTINCT r.source_file) WHERE s IS NOT NULL AND s <> ''] AS srcs
WHERE size(srcs) > 0
SET n.sources = srcs,
    n.source_backfilled_at = datetime(),
    n.source_backfilled_by = $operator
RETURN count(n) AS updated
"""

REPORT = """
MATCH (n:Entity)
OPTIONAL MATCH (n)-[r]-()
WITH n, [s IN collect(DISTINCT r.source_file) WHERE s IS NOT NULL AND s <> ''] AS srcs
RETURN count(n) AS entities,
       sum(CASE WHEN n.sources IS NULL THEN 1 ELSE 0 END) AS missing_sources,
       sum(CASE WHEN n.sources IS NULL AND size(srcs) > 0 THEN 1 ELSE 0 END) AS backfillable,
       sum(CASE WHEN n.sources IS NULL AND size(srcs) = 0 THEN 1 ELSE 0 END) AS unknowable,
       sum(CASE WHEN size(srcs) > 1 THEN 1 ELSE 0 END) AS multi_paper
"""


def report(conn) -> dict:
    rows = conn.run(REPORT)
    return dict(rows[0]) if rows else {}


def execute(conn, operator: str) -> int:
    rows = conn.run(BACKFILL, operator=operator)
    return int(rows[0]["updated"]) if rows else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--execute", action="store_true",
                        help="Run the additive source backfill (needs --approved-by).")
    parser.add_argument("--approved-by", default="",
                        help="Name of the person who approved running this against the graph.")
    args = parser.parse_args()

    if args.execute and not args.approved_by.strip():
        parser.error("--execute requires --approved-by <name>.")

    from pruner.db import Neo4jConnection
    from audit_log import log_event

    # Use the project's own Neo4j settings (.env, with Aura TLS handling), not
    # the pruner's localhost default.
    import config
    if not (config.URI and config.USERNAME and config.PASSWORD):
        raise SystemExit("NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD must be set in .env.")

    with Neo4jConnection(uri=config.URI, user=config.USERNAME,
                         password=config.PASSWORD) as conn:
        summary = report(conn)
        print(json.dumps(summary, indent=2, default=str))
        if not args.execute:
            print("\nDRY RUN -- nothing was changed. Cypher that --execute would run:")
            print(BACKFILL)
            return 0
        updated = execute(conn, args.approved_by.strip())
        log_event("graph.migration", actor=args.approved_by.strip(),
                  step="node_source_backfill", updated=updated, before=summary)
        print(f"Backfilled sources on {updated} entities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
