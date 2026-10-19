# ADM-5: node provenance and entity labels — migration plan

**Status: plan only. Nothing here has been run against the live graph.**

## The problem
`neo4j_loader/insert.py` merges every entity as `(:Entity {name})` and sets
no provenance on nodes. Provenance (`source_file`, `source_section`) exists
only on relationships. Consequences: a node cannot be traced to a paper
(PAPER-5), and every entity shares one label so queries cannot tell people
from places (PAPER-6).

## Steps
1. **Report (read-only)** — `python scripts/plan_node_migration.py`. Shows how
   many entities lack `sources`, how many can be derived from their
   relationships, how many are unknowable, and how many appear in several
   papers. Safe to run any time.
2. **Back up** — export the graph (Aura snapshot or `apoc.export`) before any
   write. Needed for steps 3 and 5.
3. **Source backfill (additive)** — `python scripts/plan_node_migration.py
   --execute --approved-by <name>` sets `n.sources` (a list of paper names),
   `n.source_backfilled_at` and `n.source_backfilled_by`. Never deletes or
   relabels. Entities with no relationship provenance are left alone and
   reported as unknowable.
4. **Fix the loader** — change `insert.py` to set `n.sources` (append, do not
   overwrite) on both endpoints during the MERGE so new data is correct. Not
   yet done; do after step 3 so old and new agree.
5. **Entity labels (needs a decision)** — choose a label scheme (e.g. Person,
   Group, Place, Practice, Item, Concept), decide how entities are classified
   (rules, LLM, or manual list), dry-run the classification and review the
   counts, then add labels *in addition to* `:Entity` so retrieval keeps
   working. Removing `:Entity` is a separate, later change because retrieval
   and the feedback tools match on it.

## Needs approval from the project owner
- Running step 3 or 5 against the live Aura graph.
- The label scheme and classification method for step 5.

Every executed step is written to the audit log (`graph.migration`) with who
approved it.
