"""Undo one load, by the run id add_triples stamped on it.

add_triples has written a shared run_id onto every relationship of a load
since 2026-10-05, with a docstring explaining that one call is one run so
that "everything from this load" stays queryable. Nothing ever read it
back, so in practice a load was a one-way write and
tests/test_insert.py's docstring said as much.

That became a sharper problem when approving a paper in the admin UI
started an extraction: a reviewer approves in one click, and the triples
reach the production graph with no further review. This is the way back.

Usage:
    python -m neo4j_loader.rollback <run_id> --dry-run   # what would go
    python -m neo4j_loader.rollback <run_id>             # actually delete
"""

import argparse

from neo4j_loader.connection import get_driver

_COUNT = (
    "MATCH ()-[r]->() WHERE r.run_id = $run_id RETURN count(r) AS c"
)
_DELETE = (
    "MATCH ()-[r]->() WHERE r.run_id = $run_id DELETE r RETURN count(r) AS c"
)
# The nodes this run's relationships hang off, collected BEFORE the delete
# because afterwards there is nothing left to find them by.
_ENDPOINTS = (
    "MATCH (a)-[r]->(b) WHERE r.run_id = $run_id "
    "RETURN collect(DISTINCT elementId(a)) + collect(DISTINCT elementId(b)) "
    "AS ids"
)
# insert_triple MERGEs its nodes, so deleting a run's relationships can
# strand entities that no other run referenced. They are invisible to
# retrieval but still sit in the graph and accumulate across rollbacks.
#
# Scoped to the endpoints above, NOT to every orphan in the graph. The
# first version was unscoped and, undoing a 1-triple run on 2026-10-28,
# also removed 22 unrelated pre-existing orphans. No damage that time, but
# a delete tool must never reach past what it says it touches.
_ORPHANS = (
    "MATCH (n) WHERE elementId(n) IN $ids AND NOT (n)--() "
    "AND NOT n:User AND NOT n:Conversation AND NOT n:Feedback "
    "DELETE n RETURN count(n) AS c"
)


def delete_run(run_id: str, *, driver=None, dry_run: bool = False) -> dict:
    """Remove every relationship a single load created.

    Returns {"run_id", "relationships", "orphan_nodes", "dry_run"}.

    A blank run id is refused rather than treated as "match everything",
    which is the one mistake this tool must never make.
    """
    if not (run_id or "").strip():
        raise ValueError("A run id is required; refusing to match every run.")
    run_id = run_id.strip()

    driver = driver if driver is not None else get_driver()
    with driver.session() as session:
        found = session.run(_COUNT, run_id=run_id).single()
        count = (found or {}).get("c", 0) or 0

        if dry_run or count == 0:
            return {
                "run_id": run_id,
                "relationships": count,
                "orphan_nodes": 0,
                "dry_run": bool(dry_run),
            }

        endpoints = session.run(_ENDPOINTS, run_id=run_id).single()
        ids = (endpoints or {}).get("ids") or []

        deleted = session.run(_DELETE, run_id=run_id).single()
        orphans = session.run(_ORPHANS, ids=ids).single() if ids else None
        return {
            "run_id": run_id,
            "relationships": (deleted or {}).get("c", 0) or 0,
            "orphan_nodes": (orphans or {}).get("c", 0) or 0,
            "dry_run": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete every triple a single load wrote to Neo4j."
    )
    parser.add_argument("run_id", help="The run_id add_triples printed.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be deleted and delete nothing.",
    )
    args = parser.parse_args()

    result = delete_run(args.run_id, dry_run=args.dry_run)
    verb = "Would delete" if result["dry_run"] else "Deleted"
    print(f"{verb} {result['relationships']} relationships "
          f"from run {result['run_id']}.")
    if not result["dry_run"] and result["orphan_nodes"]:
        print(f"Also removed {result['orphan_nodes']} nodes left with no "
              f"relationships.")


if __name__ == "__main__":
    main()
