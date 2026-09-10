# Neo4j Triple Pruner

Self-maintaining noise removal for the Mandi/Garo KG, built around your
project's own requirements: KG8's non-negotiable source-referencing rule,
the LLM extraction pipeline's known failure modes (UNKNOWN labels,
hallucinated relations, methodology/research-process leakage), and KG7's
human-verification requirement for LLM-generated entries.

**Verified against the real pipeline on 2026-09-09** (`kg_extractor.py`,
`main.py`, `neo4j_loader/insert.py`) — the config below now matches your
actual ingestion code rather than a guess. Three things needed more than
a rename; see "What changed" below before you run anything.

## How it works

Three tiers, run in order, every time a new batch of extractions lands:

1. **Structural checks (auto-delete).** Missing source reference on
   relationships, self-loop triples, exact duplicate relationships.
   These are unambiguous by your own project's rules, so they're deleted
   straight away — but archived to `pruned_log.jsonl` first, so nothing
   is silently lost. (Malformed extractions like `UNKNOWN` labels are
   already filtered before anything reaches Neo4j in your current
   pipeline, so there's no check for that here. The **node**-level
   version of this check is disabled — see "What changed".)
2. **Duplicate detection.** Same-labelled entities with near-identical
   names get merged (relationships redirected, name kept as an alias).
   Certain matches (case/whitespace variants) auto-merge; fuzzy-but-not-
   certain matches are flagged for review instead of merged blind.
3. **LLM-as-judge.** Each surviving relationship is checked against its
   source text for whether it's actually supported *and* actually about
   the community rather than the research process. Clearly noise (either
   check fails) → deleted. Clearly good → kept. Anything in between →
   flagged for review.

Everything Tier 2/3 isn't confident about gets a `needs_review` property
instead of being touched — that's the backend human-verification queue.
Nothing needs a human to look at *every* triple, only the ambiguous ones.

## What changed from the original draft

- **`SOURCE_PROPERTY`**: `source_ref` → `source_file`, matching what
  `neo4j_loader/insert.py` actually sets on relationships.
- **Node-level missing-source check disabled** (`pruner/rules.py`).
  `insert.py` only ever sets a source property on *relationships* —
  nodes (`MERGE (s:Entity {name: $subject})`) never get one. Left
  enabled, Tier 1 would have matched every node in the graph as
  "missing source" and `DETACH DELETE`d all of them, wiping everything
  rather than just the noise. The check is still defined
  (`find_missing_source_nodes`), just not called — re-enable it in
  `run_tier1()` only after `insert.py` is changed to set a source
  property on nodes too.
- **`SOURCE_TEXT_PROPERTY`**: `source_text` → `passage`, matching what
  `insert.py` actually stores the extracted passage as.
- **`NEO4J_USER` now also accepts `NEO4J_USERNAME`** (`pruner/config.py`),
  so it reads directly from the same `.env` the main pipeline uses
  instead of needing a duplicate variable.
- **Tier 3's judge prompt rewritten** (`pruner/llm_judge.py`). The
  original question was pure hallucination detection ("is this stated by
  the source text"). Checked against the actual leaks found in this
  project's `garo_1.pdf` run — things like
  `(Respondents)-[KNOWN_ORIGIN]->(Tibet)` — that question doesn't catch
  them: the source sentence genuinely does say that, so a faithfulness-
  only judge scores it high confidence and keeps it. The real problem is
  topical, not factual: it's a faithful extraction of a sentence
  describing the *research process*, not the community. `JUDGE_PROMPT`
  now asks both questions and returns low confidence if either fails.
- **Ollama judge backend**: URL now reads from `OLLAMA_JUDGE_URL` (was
  hardcoded to `http://localhost:11434/...`, which only resolves from
  the host machine, not from inside the `app` container — same
  container-networking issue documented in this project's own
  `docker-compose.yml`). Default model changed to `deepseek-r1:7b` to
  match the model the main pipeline already uses, so nothing extra needs
  pulling.
- **`ENTITY_CATEGORIES`**: left as-is, but note it's currently unused
  against real data — every node the pipeline creates is labelled
  `:Entity`, not one of these 16 categories, so Tier 2 dedup falls back
  to comparing everything in one bucket. Still correct, just not
  category-scoped the way this table implies. Update this if/when the
  schema is extended to real per-category node labels.
- **`BATCH_PROPERTY`**: unchanged (`batch_id`), but `insert.py` doesn't
  set it on anything yet, so `--batch-id` runs will always match zero
  rows against real data. Use `--full-scan` until batch tagging is added
  — see "Adding batch tagging" below if you want that later.

## Setup

```bash
pip install -r requirements.txt   # now includes rapidfuzz

# Point at your Aura instance — same values as this project's .env:
export NEO4J_URI="neo4j+s://0a31f83f.databases.neo4j.io"
export NEO4J_USERNAME="0a31f83f"   # NEO4J_USER also works
export NEO4J_PASSWORD="..."

# Pick one LLM backend for Tier 3, or skip it with --no-llm-judge:
export LLM_JUDGE_BACKEND="ollama"
# If running via `docker compose exec app ...`, "localhost" won't reach
# the ollama service from inside that container — use the service name:
export OLLAMA_JUDGE_URL="http://ollama:11434/api/generate"
# (Omit OLLAMA_JUDGE_URL entirely if running this directly on the host,
# where docker-compose.yml's port mapping makes localhost:11434 work.)
```

## Manual / one-off use

```bash
# See what would happen, without changing anything — always do this first:
python run_prune.py --full-scan --dry-run -v

# Actually prune the whole graph (no batch tagging yet, so this is the
# only mode that matches anything against real data):
python run_prune.py --full-scan -v

# Skip the (currently no-op without batch tagging) --batch-id mode
# entirely until insert.py sets batch_id.
```

## Working the review queue

```bash
python review_cli.py list
python review_cli.py approve <element_id> --kind node
python review_cli.py reject  <element_id> --kind relationship
```

`review.py` is deliberately just plain functions (`approve`, `reject`,
`list_flagged`) — swap `review_cli.py` for a small web page later if you
want the human-verification step to be something the team clicks through
rather than runs from a terminal; the logic underneath doesn't change.

## Adding batch tagging (optional, for future runs)

To let `--batch-id` scope a run to just the batch that just landed
(rather than always sweeping the whole graph), add one line to
`neo4j_loader/insert.py`'s `SET` clause:

```cypher
SET r.source_file = $source_file,
    r.batch_id = $batch_id,
    ...
```

and pass a `batch_id` (e.g. a timestamp or the paper name + date) through
from `main.py` at call time. Not required for this cleanup pass — this
was a deliberate scope decision, not made unprompted, since it touches
`neo4j_loader/insert.py`.

## What's deliberately NOT automatic

- **Fuzzy duplicate matches** below the auto-merge threshold are flagged,
  never merged blind — a wrong merge is harder to undo than a wrong
  delete.
- **The oversized-entity heuristic** (an entity name that looks like a
  mis-split sentence fragment, e.g. "for catching fish") only flags,
  never deletes — occasionally that's a legitimate long name.
- **Anything with no resolvable source text** skips the LLM judge
  entirely rather than guessing.
- **Node-level missing-source deletion** — disabled entirely for now,
  see "What changed" above.

## Known limitations

- **Tier 2 dedup is O(n²) per label, across the whole graph, every run.**
  Fine at capstone-project scale (hundreds to low thousands of nodes per
  label); if the production Mandi KG grows much larger, this needs an
  index-backed candidate search (e.g. a name prefix/n-gram index) instead
  of comparing every node to every other node in its label group.
- **The LLM judge costs one API call per relationship per batch.** For a
  large batch, consider batching multiple triples into one prompt, or
  only running it on relationships Tier 1/2 didn't already resolve.
- **`elementId()`** is used throughout (Neo4j 5.x). AuraDB is on 5.x by
  default, so this should be fine, but if your instance is on 4.x, swap
  these for the legacy `id()` function.

## Tuning

All thresholds live in `pruner/config.py`:
`DEDUP_AUTO_MERGE_THRESHOLD` / `DEDUP_REVIEW_THRESHOLD` (0-100 fuzzy
match score) and `LLM_JUDGE_LOW_THRESHOLD` / `LLM_JUDGE_HIGH_THRESHOLD`
(0.0-1.0 confidence). Worth tuning against a small hand-labelled sample
before trusting it on live Mandi data — same idea as your KG5 LLM
comparison task, just applied to the judge instead of the extractor.
