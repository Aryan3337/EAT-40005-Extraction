# Extraction & Verification Design — Strict Prompt Trial, Two-Step Verification, Evidence/Direction Checks

**Project:** EAT40005 Capstone, Group P85 — Mandi/Garo Knowledge Graph Extraction
**Date:** 2026-09-21
**Status:** Approved for planning (brainstorming phase complete; implementation plan to follow via writing-plans)

## 1. Context and goals

The pipeline extracts triples from academic papers about the Mandi/Garo community into
Neo4j via a local LLM (Ollama, `deepseek-r1:7b`). Prompt tweaks alone have stopped
reducing noise. Per supervisor guidance (Tanjila), the project should now prioritize
**correctness over coverage** — it is better to miss a fact than to store an incorrect
or hallucinated one, since missed facts can be added later through manual expert
verification.

This document scopes the **extraction and verification** stage of a larger
preprocessing → extraction → refinement/verification → chatbot-feedback pipeline.
Table-to-sentence preprocessing and chatbot feedback are explicitly out of scope for
this design; they are noted as future phases in §8.

### 1.1 Goals for this phase

1. Compare a strict "tacit-only" extraction prompt against the current broad prompt,
   with real measurements, not assumption.
2. Design and build a two-step extract → verify pipeline shape (per Tanjila's
   suggestion), as a second, independently-measured configuration.
3. Add an evidence check (does the source sentence support the triple) and a
   direction/ontology check (is the predicate's subject/object direction plausible),
   both able to run pre-upload, on CSV output, never touching the production Neo4j
   instance.
4. Build an automated precision/recall/F1 (+ hallucination rate, triples/page) scoring
   harness against the existing 148-triple manual ground truth, since no such script
   exists today (all prior scoring in `Prompt_Iteration_Log.xlsx` was done by hand).
5. Keep every prompt variant in a versioned file (not an inline string) so variants can
   be diffed and logged, and document the reasoning behind each design decision.

### 1.2 Non-goals for this phase

- Table-to-sentence preprocessing for the new tabular source data (future phase).
- Chatbot-side feedback loop (future phase).
- Full Jaccard/TF-IDF near-duplicate triple dedup tuning — the scorer's "lenient match"
  reuses a Jaccard similarity technique, but a dedicated dedup-tuning pass across a
  larger corpus is future work (§8).
- Any change to `neo4j_loader/insert.py`, `main.py`'s production call path, or the live
  Neo4j (Aura) instance. Everything in this design operates on CSV files produced by
  `test_extraction.py`-style scripts.
- Actually executing the new prompts end-to-end against `deepseek-r1:7b` — Ollama in
  this environment only runs inside a Docker container this session cannot reach (see
  §7, Execution Plan). This phase builds and validates the harness/checks against
  ground truth and already-existing historical extraction CSVs in `output/`; running
  the new prompt variants happens afterward, on the author's machine.

## 2. Current state (as found)

- `kg_extractor.py`'s live prompt ("PR008 / Variant A round 4") already documents, in
  its own header comment, that subject collapse to `GaroCommunity` is still ~93% on a
  full-paper run (vs. 61% in the ground truth), ~32% of predicates still violate the
  `UPPER_SNAKE_CASE` rule, and predicate fragmentation is unresolved.
- `test_extraction_variants.py`'s `baseline`/A/B/C/D prompt variants are from an earlier
  round (based on the older "PR007") and have drifted from the current live prompt —
  they are a different reference point, not interchangeable with it.
- `subject_specificity.py` already performs sentence-level, spaCy-based subject
  correction (rewriting `GaroCommunity`/`GaroPeople` to a more specific noun phrase when
  the source sentence supports it), with numerous conservative guards. This runs
  automatically in `main.py` and `run_page_pipeline.py`.
- `Extraction_Check.flag_artifact_triples` is a hand-built, reactively-grown keyword
  list (~40 terms + predicate-substring markers) for research-methodology leakage. It
  hard-rejects (not just warns) in `main.py`.
- `pruner/` is a **post-Neo4j-upload** cleanup package with three tiers: structural
  auto-delete (Tier 1), fuzzy entity-name dedup via `rapidfuzz` (Tier 2), and an
  LLM-as-judge pass (Tier 3, `pruner/llm_judge.py`) that already asks a combined
  "is this evidenced AND is this topical (not research-process)" question, banding
  results into auto-delete / flag-for-review / keep. Nothing in `main.py` or
  `run_page_pipeline.py` calls into `pruner/` — it is a separate, optional pass a human
  runs later against the live graph. There is no direction/ontology check anywhere in
  the codebase.
- `deduplicate_triples()` (used pre-upload) is exact-match only, on normalized
  subject|predicate|object. Near-duplicate/paraphrase-level dedup exists only as fuzzy
  **entity-name** matching, post-upload, in `pruner/dedup.py`.
- The 148-triple manual ground truth lives in `KG_extraction_Garo_1.xlsx` (`Final
  Triples` sheet, joined to `Sentence Extraction` for verbatim source sentences),
  spanning pages 1–7 of `garo_1.pdf`. `Prompt_Iteration_Log.xlsx`'s `Prompt Iteration
  Log` sheet already has the target metric shape (Prompt ID, Precision/Recall/F1 strict
  and lenient, failure-mode notes) for page 3 specifically, computed by hand across
  several prior rounds — no scoring script exists.
- `output/` already contains several historical extraction CSVs
  (`garo_1_page3_test.csv`, `garo_1_page3_variant{baseline,A,B,C}.csv`,
  `garo_1_page{1,4,5}_kg.csv`, `garo_1_fullpaper_variantA.csv`) that can validate a new
  scorer against already-known, already-logged results without needing to run Ollama.

## 3. Design overview

Three prompt configurations will be built and compared through one shared scoring
harness:

- **(A) Current live prompt** — `kg_extractor.make_extraction_prompt()`, unmodified.
  Continuity baseline against the existing log.
- **(B) Strict tacit-only prompt, single pass** — new, standalone. Directly answers
  Tanjila's "try a strict prompt" suggestion.
- **(C) Broad extraction (de-hubbed) → verification pass, two steps** — new. Directly
  answers Tanjila's two-step suggestion.

The direction/ontology check (deterministic, no LLM) can additionally run on the output
of any of the three, including (A), since it costs nothing — this lets us see its effect
in isolation as a fourth comparison point.

```
                    ┌────────────────────────────────────────────┐
                    │              existing, unchanged             │
                    │  pdfplumber → chunk_text() → dedup()          │
                    └───────────────────┬────────────────────────┘
                                         │
                     ┌───────────────────┼───────────────────┐
                     │                   │                   │
               (A) live prompt     (B) strict prompt   (C) broad-v2 prompt
                     │                   │                   │
                     │                   │             ┌─────┴─────┐
                     │                   │             │ verify_tacit│  (new LLM call,
                     │                   │             │ _evidence   │   pluggable judge_fn,
                     │                   │             │ pass        │   keep/review/reject
                     │                   │             └─────┬─────┘   bands)
                     │                   │                   │
                     └─────────┬─────────┴─────────┬─────────┘
                                │                   │
                        (optional, all 3) direction/ontology check
                                │                   (deterministic, lexicon-based)
                                ▼
                     eval/scorer.py  →  strict/lenient P/R/F1,
                                        hallucination rate, triples/page
                                ▼
                        eval/results.csv (new, git-tracked, append-only)
```

Nothing here touches `neo4j_loader` or calls `add_triples()`. All new scripts follow
the existing project convention (`test_extraction.py`, `run_page_pipeline.py`) of
importing pipeline primitives unmodified rather than re-implementing them.

## 4. Prompt files and versioning

New `prompts/` directory. Plain `.txt` templates with a single `{passage}`
placeholder, loaded via a small `prompts/loader.py` (`load_prompt(name: str) ->
Callable[[str], str]`). This replaces the existing pattern in
`test_extraction_variants.py`, which embeds each variant as a Python function
returning an f-string — per the project's own constraint, prompt content should live
in versioned files a diff/log can track independently of code changes.

Files:

- `prompts/extraction_broad_v2.txt` — a copy of the current live prompt (§2), with one
  change: the opening framing "identify every ... knowledge **about the Garo/Mandi
  community**" is reworded to "identify every ... knowledge **from this passage, in the
  Garo/Mandi cultural context**." The domain scope is unchanged; the implicit "the
  subject of every fact is the community" framing is removed, since that framing
  actively worked against the prompt's own later instruction to match the sentence's
  own specificity.
- `prompts/extraction_strict_tacit_v1.txt` — new. Opens with an explicit definition of
  tacit knowledge for this project ("unwritten, experience-based, practice-embedded
  knowledge — how something is done, why it matters, what it means — as opposed to
  demographic facts, bibliographic facts, or statements about the research process
  itself"), 4–6 worked examples of clear tacit-knowledge triples and 4–6 worked
  non-examples (demographic fact, citation, research-methodology fact, a vague/
  unverifiable claim), and the same structural output rules as the broad prompt
  (CamelCase entities, `UPPER_SNAKE_CASE` predicates, one triple per value, exact
  `SENTENCE REF`). If a passage contains nothing that clears the tacit-knowledge bar,
  the prompt instructs the model to output nothing rather than force a weak triple —
  directly implementing "better to miss than to store wrong."
- `prompts/verify_tacit_evidence_v1.txt` — new. Takes one candidate triple + its source
  sentence and asks two questions in one call, mirroring the proven pattern in
  `pruner/llm_judge.py`'s `JUDGE_PROMPT`: (1) is this relationship stated or clearly
  implied by the source sentence (evidence/faithfulness), (2) does it meet the same
  tacit-knowledge definition used in the strict prompt. Returns
  `{"decision": "keep"|"reject", "confidence": <0.0-1.0>, "reason": "<one sentence>"}`.
  Deliberately does **not** re-ask "is this about the community / not research
  methodology" — that question is already answered by the strict tacit-knowledge
  definition (tacit knowledge and research-methodology description are mutually
  exclusive by construction), so asking it a third time (extraction skip-list → this
  verify pass → the existing `flag_artifact_triples` keyword filter, which stays as a
  safety net) would be redundant, not additive.

A companion `prompts/CHANGELOG.md` records, per version, what changed and why — the
doc-note requirement from the project constraints, kept out of the `.txt` files
themselves so it never leaks into what is actually sent to the LLM.

## 5. Verification pass (two-step configuration, "C")

New module `verification/verify_pass.py`, structured like `pruner/llm_judge.py`
(pluggable backend, so it can be unit-tested without Ollama):

```python
def verify_triple(subject: str, predicate: str, obj: str, source_sentence: str,
                   judge_fn: Callable[..., tuple[str, float, str]]) -> VerifyResult:
    ...
```

- `judge_fn` signature: `(subject, predicate, obj, source_sentence) -> (decision, confidence, reason)`.
- Real backend: `judge_with_ollama`, adapted from `pruner/llm_judge.py`'s existing
  Ollama backend (same `_parse_response` JSON-extraction logic, reused not
  reimplemented), pointed at `verify_tacit_evidence_v1.txt`.
- Test backend: a mock `judge_fn` returning fixed responses, used in unit tests — no
  Ollama dependency for development or CI.
- Confidence bands (mirroring `pruner/config.py`'s existing
  `LLM_JUDGE_LOW_THRESHOLD`/`LLM_JUDGE_HIGH_THRESHOLD` pattern, new config values
  scoped to this module so they can be tuned independently of the post-upload pruner):
  - `< VERIFY_LOW_THRESHOLD` → reject (excluded from the refined CSV).
  - `>= VERIFY_HIGH_THRESHOLD` → keep.
  - in between → **not silently dropped nor silently kept** — written to a
    `*_reviewed_out.csv` audit file for manual follow-up, same spirit as
    `subject_specificity.py`'s `write_corrections_log`. This matches "missed facts can
    be added later through manual expert verification": ambiguous candidates are held
    for a human, not defaulted to correctness-over-coverage on the pipeline's own guess.

## 6. Direction/ontology check

New module `verification/direction_check.py`. Given the schema has no real entity-type
labels (every node is `:Entity`; `pruner/dedup.py`'s own notes already confirm this),
full type-checking isn't available. Scope decided with the user: start with a
**curated predicate-direction lexicon**, matching the existing `ARTIFACT_KEYWORDS`
style already used in `Extraction_Check.py`, rather than the heavier option of reusing
`subject_specificity.py`'s spaCy grammatical-subject detection to cross-check triple
roles against sentence roles.

```python
# verification/predicate_directions.py
DIRECTIONAL_PREDICATES = {
    "PROHIBITS": {
        "subject_keywords": ["rule", "law", "custom", "taboo", "tradition", "authority", "council"],
        "object_keywords": ["fishing", "hunting", "activity", "area", "practice", "place"],
    },
    "REQUIRES": {...},
    "GOVERNS": {...},
    "TEACHES": {...},
    # extend as real predicates are observed in ground truth / new runs
}

def check_direction(subject: str, predicate: str, obj: str) -> DirectionResult:
    """Returns flagged=True with a reason if subject/object keyword shape looks
    swapped against the predicate's expected direction. Predicates not in the
    lexicon are never flagged (silence, not a guess)."""
```

The lexicon seeds from predicates already observed in the ground truth's `Final
Triples`/`Fact Extraction` sheets and the strict prompt's own worked examples, so it
isn't built from imagination. Extending it to the spaCy-based cross-check is documented
here as a future option (§8) if the lexicon proves too narrow once more data is
processed — deliberately not built now, per "prefer the smallest change that can be
measured."

## 7. Test harness

### 7.1 Ground truth loader — `eval/ground_truth.py`

- `load_final_triples(xlsx_path=DEFAULT_GT_PATH) -> list[GroundTruthTriple]` — parses
  the `Final Triples` sheet, reusing the exact `(Subject)-[PREDICATE]->(Object)` regex
  already in `kg_extractor.parse_ollama_blocks`, so ground truth and pipeline output are
  parsed identically. Each result carries `ref`, `sentence_num`, `subject`, `predicate`,
  `object`, `page`, `section`.
- `load_sentences(xlsx_path) -> dict[str, str]` — `Sentence #` → verbatim sentence, from
  the `Sentence Extraction` sheet. Used by scorer diagnostics and by verify-pass unit
  tests that want a real sentence without touching the pipeline.
- `triples_for_pages(triples, pages: list[str]) -> list[GroundTruthTriple]` — filter
  helper (the sheet's `Page` column includes values like `"1-2"`, so this does a
  substring/contains match on the page token, not pure equality).
- Read-only: this module never writes to `KG_extraction_Garo_1.xlsx`.

### 7.2 Scorer — `eval/scorer.py`

- `normalize(subject, predicate, obj) -> tuple[str, str, str]` — lowercase + whitespace
  strip.
- `jaccard_similarity(a: tuple[str,str,str], b: tuple[str,str,str]) -> float` — token-set
  Jaccard over the combined subject+predicate+object text of both triples.
- `match_strict(a, b) -> bool` — normalized exact equality on all three fields.
- `match_lenient(a, b, threshold=LENIENT_THRESHOLD) -> bool` — `jaccard_similarity >=
  threshold`. `LENIENT_THRESHOLD` starts as a named constant tuned against page 3 (the
  one page with prior hand-scored "lenient" judgments in `Prompt_Iteration_Log.xlsx` to
  calibrate against) before being trusted on other pages.
- `score(extracted: list[dict], ground_truth: list[GroundTruthTriple]) -> ScoreReport` —
  greedy one-to-one matching (each ground-truth triple claimable by at most one
  extracted triple, and vice versa, checked strict-first then lenient-first) to avoid
  double-counting. Returns a dataclass: `tp_strict, fp_strict, fn_strict, tp_lenient,
  fp_lenient, fn_lenient, precision_strict, recall_strict, f1_strict, precision_lenient,
  recall_lenient, f1_lenient, hallucination_rate, triples_per_page`.
- `ScoreReport` intentionally mirrors the column set already in
  `Prompt_Iteration_Log.xlsx`'s `Prompt Iteration Log` sheet.

### 7.3 CLI — `eval/run_eval.py`

```
python -m eval.run_eval output/garo_1_page3_variantA.csv --pages 3 --label "Variant A (broad-v2)"
```

Appends one row to a new, git-tracked `eval/results.csv` (separate from
`Prompt_Iteration_Log.xlsx` — automated output is kept out of the hand-curated log to
avoid corrupting its manually-written notes/formatting; rows can be copied across by a
human when wanted).

### 7.4 Validation without Ollama

The scorer's own correctness is checked against real historical data already in the
repo, before it is trusted on anything new:

- `eval/scorer.py` run against `output/garo_1_page3_test.csv` (the exact file the
  logged "PR007 (baseline)" row used) must land close to that row's recorded TP-strict
  = 11/23, TP-lenient = 16/23.
- Run against `output/garo_1_page3_variantbaseline.csv` (the file the logged "PR007
  (baseline, rerun)" row used) must land close to TP-strict = 2/23, TP-lenient = 14/23.
- These become regression tests (`tests/test_scorer_golden.py`), not just a one-off
  sanity check — they pin the scorer's matching behavior against known-good numbers so
  future changes to `match_lenient`'s threshold or the matching algorithm can't
  silently drift without a visible test failure.

### 7.5 Verification pipeline wiring — `run_verification_pipeline.py`

Sibling script to `run_page_pipeline.py`, following the same "import unmodified,
never touch Neo4j" convention as `test_extraction.py`:

```
python run_verification_pipeline.py output/garo_1_page3_variantA.csv --direction-check --verify
```

Takes an already-produced extraction CSV, optionally runs the verify pass (§5) and/or
the direction check (§6), and writes:

- `<name>_refined.csv` — surviving triples.
- `<name>_reviewed_out.csv` — borderline verify-pass results (audit trail, never
  silently dropped).
- `<name>_direction_flags.csv` — triples the direction check flagged (flag-only, never
  auto-deleted, same conservative posture as the existing oversized-entity heuristic in
  `pruner/rules.py`).

Never imports `neo4j_loader`, never calls `add_triples()`.

## 8. Future work (explicitly out of scope here)

- Table-to-sentence preprocessing for new tabular source data.
- Chatbot-side feedback loop.
- Extending the direction check from the curated lexicon to a spaCy-based
  grammatical-role cross-check (reusing `subject_specificity.py`'s subject detection),
  if the lexicon proves too narrow.
- Dedicated near-duplicate **triple** dedup tuning (Jaccard/TF-IDF) across a larger
  corpus, beyond the scorer's reuse of Jaccard similarity for lenient ground-truth
  matching.
- Wiring the verification pass and direction check into `main.py`'s production path,
  once metrics from this phase justify a specific configuration.
- Node-level source tracking and batch tagging in `neo4j_loader/insert.py` (already
  flagged as unfinished in `PRUNER_README.md`, unrelated to this phase's scope but
  adjacent).

## 9. Testing strategy summary (TDD)

Note on convention: the existing root-level `test_extraction.py` /
`test_extraction_variants.py` are manual harness scripts (they print output; they don't
assert anything) — the repo has no automated unit-test setup today (no `pytest` in
`requirements.txt`, no `tests/` directory). This phase introduces `pytest` as a new dev
dependency and a `tests/` directory for real automated tests, kept distinct from the
existing root-level manual-harness naming convention.

All new logic gets tests written first, and all of it is testable without Ollama:

1. `eval/scorer.py` — unit tests for `normalize`, `jaccard_similarity`, `match_strict`,
   `match_lenient` with hand-crafted triple pairs; golden regression tests against
   `output/garo_1_page3_test.csv` and `output/garo_1_page3_variantbaseline.csv` (§7.4).
2. `eval/ground_truth.py` — unit test that `load_final_triples` returns 148 rows total
   and the page-3 subset returns 23, matching the counts already documented in
   `Prompt_Iteration_Log.xlsx`'s `Page3_Ground_Truth` sheet.
3. `verification/direction_check.py` — unit tests with crafted examples per lexicon
   entry, including at least one deliberately-reversed case per predicate.
4. `verification/verify_pass.py` — unit tests with a mocked `judge_fn` covering all
   three confidence bands (reject / review / keep).
5. `run_verification_pipeline.py` — an integration-style test that feeds a small
   crafted CSV through with a mocked judge and asserts the three output files contain
   the expected rows.

## 10. Execution plan (given Ollama constraint)

This session cannot reach the Docker-hosted Ollama instance, so the prompts and verify
pass are built and unit-tested here, but not run end-to-end here. After this phase:

1. Run `extraction_strict_tacit_v1.txt` and `extraction_broad_v2.txt` (→ verify pass)
   against the same ground-truth pages already used historically (page 3 at minimum,
   ideally 1, 4, and 5 too, since those also have existing baseline CSVs to compare
   against) via a small new harness script analogous to `test_extraction_variants.py`.
2. Score each configuration with `eval/run_eval.py` against the ground truth.
3. Compare precision/recall/F1 (strict + lenient), hallucination rate, and
   triples/page across (A) live prompt, (B) strict-only, (C) broad-v2+verify, each
   with and without the direction check layered on.
4. Only then decide which configuration (if any) is promoted toward `main.py`'s
   production path — a separate, later decision, not part of this design.
