"""
Nothing gets hard-deleted without a paper trail first.

Your client's traceability requirement (KG8: "every entry must link to a
document ID, interview ID, or paper... non-negotiable") is a strong signal
that quietly destroying data -- even data you're confident is noise -- is
the wrong default for this project. So every deletion this pruner makes
is archived to an append-only JSONL log *before* the Cypher DELETE runs.
If your marking/audit process (QT3's hallucination audit, for instance)
ever needs to know what was removed and why, it's all in one file.

This is a local file by design (simple, diffable, easy to attach as
evidence in a sprint report). Swap `log_removal` for a write into Neo4j
itself (e.g. an `:Pruned` archive subgraph) if you'd rather keep it in
the database.
"""

import json
import os
from datetime import datetime, timezone

DEFAULT_LOG_PATH = os.environ.get("PRUNE_LOG_PATH", "pruned_log.jsonl")


def log_removal(record: dict, log_path: str = DEFAULT_LOG_PATH):
    """Append one removed/merged item to the audit log.

    `record` should describe what was removed and why, e.g.:
        {
            "action": "delete" | "merge",
            "tier": 1 | 2 | 3,
            "reason": "missing_source",
            "batch_id": "...",
            "element": {...node or relationship properties...},
        }
    """
    entry = dict(record)
    entry["logged_at"] = datetime.now(timezone.utc).isoformat()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def read_log(log_path: str = DEFAULT_LOG_PATH):
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
