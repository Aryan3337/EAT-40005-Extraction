"""
Entry point: prune_batch().

Call this right after your ingestion step finishes writing a new set of
extractions into Neo4j -- i.e. as step 7 tacked onto your existing 6-step
prompting pipeline, using the same batch_id you tagged those nodes and
relationships with. That's what makes this "self-maintaining": nothing
needs to be run by hand for it to happen.

(Note: the current insert.py doesn't set batch_id yet -- see
pruner/config.py's BATCH_PROPERTY comment. Until it does, call this with
batch_id=None / --full-scan.)

Order matters: Tier 1 first (removes the clear noise so Tier 2/3 aren't
wasting fuzzy-matching or LLM calls on garbage), then Tier 2 (dedup --
needs Tier 1's surviving nodes), then Tier 3 (LLM judge -- the most
expensive check, run last and only on what's left).
"""

import logging

from . import dedup, llm_judge, rules
from .db import Neo4jConnection

logger = logging.getLogger("pruner")


def prune_batch(batch_id=None, dry_run=False, run_llm_judge=True, judge_fn=None, conn=None):
    """Runs all three tiers against a batch (or the whole graph if
    batch_id is None). Returns a combined summary dict.

    dry_run=True runs every check and writes to the audit log as if it
    were deleting/merging/flagging, but makes no changes to the graph --
    use this first on a new batch to see what the pruner *would* do.
    """
    owns_conn = conn is None
    conn = conn or Neo4jConnection()
    try:
        logger.info("Tier 1 (structural checks) — batch=%s dry_run=%s", batch_id, dry_run)
        tier1 = rules.run_tier1(conn, batch_id, dry_run)
        logger.info("Tier 1 result: %s", tier1)

        logger.info("Tier 2 (duplicate detection)")
        tier2 = dedup.run_tier2(conn, batch_id, dry_run)
        logger.info("Tier 2 result: %s", tier2)

        tier3 = {"skipped": True}
        if run_llm_judge:
            logger.info("Tier 3 (LLM-as-judge)")
            tier3 = llm_judge.run_tier3(conn, batch_id, dry_run, judge_fn)
            logger.info("Tier 3 result: %s", tier3)

        return {"tier1_structural": tier1, "tier2_duplicates": tier2, "tier3_llm_judge": tier3}
    finally:
        if owns_conn:
            conn.close()
