"""
Central configuration for the triple pruner.

Everything schema-specific lives here so the rest of the codebase never
hardcodes a property name.

--- Verified against the actual pipeline on 2026-09-09 ---
(kg_extractor.py / main.py / neo4j_loader/insert.py, EAT-40005-Extraction)
The values below now match the real ingestion code, not the original
guesses. See the two "IMPORTANT" notes below for the two things that
needed more than a rename.
"""

import os

# --- Connection -------------------------------------------------------
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
# The main pipeline's .env calls this NEO4J_USERNAME, not NEO4J_USER --
# accept either so this tool works against the same .env without
# duplicating the variable.
NEO4J_USER = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

# --- Schema property names ---------------------------------------------
# The property that stores the document/paper a relationship traces back
# to. neo4j_loader/insert.py sets this as `r.source_file` (e.g.
# "garo_1.pdf") on every relationship it creates.
#
# IMPORTANT: insert.py only ever sets this on RELATIONSHIPS, never on
# nodes (MERGE (s:Entity {name: $subject}) sets no source property at
# all). That's a real gap against KG8's "every entry must link to a
# source" requirement as applied to entities, but it's how the current
# ingestion code actually works -- so Tier 1's node-level "missing
# source" check has been disabled in rules.py rather than left to auto-
# delete every node in the graph. See the note there before re-enabling
# it, and see if backfilling a source onto nodes is worth doing in
# insert.py itself before turning that check back on.
SOURCE_PROPERTY = "source_file"

# The property tagging every node/relationship created in one ingestion
# run. The current insert.py does NOT set this on anything, so
# --batch-id scoped runs will always match zero rows -- use --full-scan
# until/unless batch_id tagging is added to insert.py's SET clause:
#   SET r.source_file = $source_file, r.batch_id = $batch_id, ...
BATCH_PROPERTY = "batch_id"

# Where the raw source text for a triple can be found, for the LLM judge.
# insert.py stores the extracted passage as `r.passage` (not
# `source_text`) -- SOURCE_TEXT_PROPERTY updated to match.
SOURCE_TEXT_MODE = "property"
SOURCE_TEXT_PROPERTY = "passage"

# Property the LLM judge writes its score to, and the property flagged
# items get their reason written to.
CONFIDENCE_PROPERTY = "llm_confidence"
# Note: relationships in Neo4j can't carry extra labels (only nodes can),
# so the review queue is implemented as a boolean property on BOTH nodes
# and relationships, rather than a `:NeedsReview` label. Keeps the logic
# identical for both element types.
REVIEW_FLAG_PROPERTY = "needs_review"
REVIEW_REASON_PROPERTY = "review_reason"
REVIEW_FLAGGED_AT_PROPERTY = "flagged_at"

# --- Entity schema -------------------------------------------------------
# IMPORTANT: the real pipeline doesn't use these 16 categories at all --
# every node insert.py creates is labelled just `:Entity`
# (MERGE (s:Entity {name: $subject})), regardless of what kind of thing
# it is. pruner/dedup.py's label grouping falls back to the node's own
# label when nothing here matches, so with the real data every node ends
# up in a single "Entity" bucket for dedup comparison -- which works, it
# just means Tier 2 doesn't get the benefit of category-scoped comparison
# this table was designed for. Left in place (harmless, and useful if the
# schema is ever extended to real per-category labels), but don't expect
# it to narrow anything against the current graph.
ENTITY_CATEGORIES = {
    "ID": "Identity",
    "LOC": "Location",
    "TOOL": "Tool",
    "FOOD": "Food",
    "SSN": "Season",
    "ATT": "Attribute",
    "PROD": "ProductAspect",
    "INFO": "Infosource",
    "GRP": "Group",
    "FAC": "Factor",
    "DATE": "Date",
    "TIME": "Time",
    "CNT": "Countable",
    "CON": "Concept",
    "ACT": "Activity",
    "COST": "Cost",
}
KNOWN_LABELS = set(ENTITY_CATEGORIES) | set(ENTITY_CATEGORIES.values())

# --- Tier 2: duplicate detection thresholds -----------------------------
# Similarity ratio (0-100, via rapidfuzz) above which two same-labelled
# entities are considered certain duplicates and merged automatically.
DEDUP_AUTO_MERGE_THRESHOLD = 95
# Below AUTO_MERGE but above this, flag for human review instead of
# merging blind.
DEDUP_REVIEW_THRESHOLD = 85

# Heuristic: entity names longer than this many words are usually a
# mis-split sentence fragment (e.g. "for catching fish" as an ACT) rather
# than a real entity. Flagged, not auto-deleted.
MAX_SENSIBLE_ENTITY_WORDS = 6

# --- Tier 3: LLM-judge thresholds --------------------------------------
# Confidence score (0.0-1.0) the judge returns. See llm_judge.py's
# JUDGE_PROMPT -- this now scores BOTH textual support AND topical
# relevance (is it a community fact vs. a description of the research
# process), not just hallucination detection, since the leaks actually
# found in this project's data (page-3/7 methodology and demographic-
# survey content) were textually faithful to their source sentence and
# would have scored high on a faithfulness-only check.
LLM_JUDGE_LOW_THRESHOLD = 0.3   # below this -> auto-delete as noise
LLM_JUDGE_HIGH_THRESHOLD = 0.7  # above this -> keep, no review needed
# Anything in between is flagged for review.

# Skip the LLM judge entirely if no source text/lookup is available for
# a triple (it will just fall through as "keep" -- Tier 1 already caught
# missing-source triples).
