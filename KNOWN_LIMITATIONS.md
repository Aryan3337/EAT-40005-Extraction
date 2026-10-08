# Known limitations

What this system does not do, with the evidence for each. Written for
whoever inherits the project.

Everything here was measured, not estimated. Where a number appears, the
command that produced it is given so it can be re-checked.

Last updated 2026-10-07. Dated measurements below are kept as recorded even
where later work changed the picture; a dated "**Update:**" note is added
wherever the original text would now mislead, rather than rewriting history.

---

## 1. The knowledge graph is small, and deliberately so

45 triples across three papers, from 578 extracted candidates.

| Paper | Extracted | Kept | Well-formedness | Grounding | Quote |
|---|---|---|---|---|---|
| garo_1 | 220 | 16 | 39 | 195 | 70 |
| garo_2 | 198 | 24 | 54 | 156 | 70 |
| garo_3 | 160 | 5 | 26 | 140 | 127 |
| **Total** | **578** | **45** | | | |

A triple can be flagged by more than one gate, so the flag columns do not
sum to the rejected count.

This is the intended trade. The graph feeds a chatbot with no human review
step, so a wrong fact reaches an end user directly while a missing one only
means the chatbot knows slightly less. The gates are a hard gate: a flagged
triple is dropped, not queued.

Reproduce:

```bash
python run_verification_pipeline.py output/garo_1_kg.csv \
    --wellformedness-check --grounding-check --quote-check --pdf papers/garo_1.pdf
```

## 2. garo_3 contributes almost nothing, and the reason is its PDF

127 of garo_3's 160 candidates fail the quote gate — 79%, against 32% and
35% for the other two papers.

The quote gate checks that a triple's cited sentence appears verbatim on its
own page of the source PDF. A failure rate that far out of line indicates
the PDF's text layer does not match what the model read — most likely a
two-column layout or a scan, where `pdfplumber` returns text in an order
that does not reconstruct into the sentences the model quoted.

This is a text-extraction problem, not a model problem. Do not treat it as a
prompt issue.

## 3. "Where do the Garo live?" has no answer

No location triple survived gating. Asking the chatbot an obvious
geographical question returns language facts instead, because keyword
ranking falls back to whatever matches "garo".

This matters for choosing demo questions. Questions the graph can answer
well concern language use, bilingualism, population and religion. Verify
before relying on any question:

```bash
python -c "
import csv
from rag import question_keywords, score_triple
rows = [r for p in ['garo_1','garo_2','garo_3']
        for r in csv.DictReader(open(f'output/{p}_kg_refined.csv', encoding='utf-8'))]
kw = question_keywords('YOUR QUESTION HERE')
print(sorted(((score_triple(r, kw), r['subject'], r['predicate'], r['object'])
              for r in rows), reverse=True)[:5])
"
```

**Update, 2026-10-05: resolved.** The retrieval-ranking fix described in
limitation #20 surfaces `GaroCommunity -[LIVING_IN]-> Mymensingh` and
`-[RESIDENTS]-> GaroHills_Meghalaya` for this exact question, verified live
in the browser. A curated stemming fix on 2026-10-07 (see #21) separately
closed a "live" vs "living" keyword-matching gap that had been burying this
same triple under generic noise for some phrasings.

## 4. The graph is a star, not a graph

Of 67 distinct entities across the 45 triples, **59 appear exactly once**.
`GaroCommunity` touches 13 triples; the next-largest hub is a bibliography
citation (`Pütz_1991`, 5).

A knowledge graph earns its name from traversal — "what connects X to Y".
This shape cannot do that. Almost everything either hangs off the one hub or
is isolated.

Two causes:

- `insert_triple` does `MERGE (s:Entity {name: $subject})`, matching on the
  name string alone. Nothing reconciles entities, so `GaroCommunity` and
  `Garo_People` are two separate nodes for the same people.
- Bibliography citations are extracted as entities. `Pütz_1991` is a
  reference, not a thing in the world.

Fix entity resolution before growing the KG. It gets harder with every paper
added.

**Update, 2026-10-07:** this same hub dominance (`GaroCommunity` on 13 of 45
triples) turned out to be the root cause of two separate-looking problems
investigated the same day: the synthesizer padding short answers with
off-topic evidence (#23), and no single relevance-score threshold being able
to separate "genuinely about this question" from "just mentions Garo" for
the sources panel (#22). Both are this limitation surfacing downstream, not
independent defects.

## 5. The predicate vocabulary is unbounded

32 distinct predicates across 45 triples; 26 used exactly once.

Five describe language use and none match each other: `LANGUAGE_USED`,
`HAS_LANGUAGE_Maintenance`, `EXTENT_OF_USE`, `IS_USED_IN`,
`Emphasizes_Languages`.

`clean_relation` only uppercases and replaces non-alphanumerics, so whatever
the model emits becomes a relationship type. Each new paper adds roughly ten
novel single-use types. At 23 papers that is ~250 types for ~350 edges, and
no one can write a reliable `MATCH ()-[r:USES_LANGUAGE]->()` against it.

The fix is a controlled vocabulary in the extraction prompt, which only
takes effect on re-extraction (~1.2 h/paper), or a canonical mapping applied
at load time in `neo4j_loader/cleaner.py`.

## 6. The read path is a full scan with no index

`Neo4jRAGSkeleton.query` matches `(s:Entity)-[r]->(o:Entity)` and tests
`CONTAINS` against five properties per relationship. There is no index and
no full-text index.

Free at 45 triples and fine into the low thousands. It is the documented
ceiling on this read path: a few tens of thousands of relationships will
need a full-text index and a different query shape. `FETCH_LIMIT = 500`
bounds the worst case so an unexpectedly large graph degrades rather than
loading everything into memory.

## 7. Feedback is collected but unreadable

The thumbs up/down and comment box work. The data is written to the
browser's `SharedPreferences` and goes nowhere else — there is no
`POST /feedback` endpoint and no storage.

If a user marks fifty answers unhelpful, nobody on the team can ever see
those fifty signals, and they are lost when the browser data is cleared.

Needs an endpoint and a store before the feature is worth anything beyond a
demonstration.

## 8. Authentication is two hardcoded accounts, checked in the browser

`auth_service.dart` compares against literal credentials in the Dart source
and persists a session in `SharedPreferences`. There is no server-side auth,
no password hashing and no session validation.

Anyone reading the published JavaScript can see the credentials.

The admin upload endpoint is protected separately by a server-side shared
secret (`ADMIN_UPLOAD_SECRET`), because a public endpoint that runs LLM work
on upload is an open invitation to burn the budget. That secret is the only
real access control in the system.

Real authentication is the top security gap for whoever inherits this.

## 9. The confidence framework does not gate extraction, and its verdicts are unstable

Three separate problems, as originally measured on 2026-10-04. The wiring
status and the instability's root cause have both since been revised below
— read the update notes, not just the original text.

**It is not wired to extraction.** `grep -rn "confidence_framework\|run_confidence_check" --include=*.py .`
returns nothing outside the module itself. Extraction does not consult it.

**Update, 2026-10-05:** it is now wired to paper *admission*, which is the
context this limitation was actually written about — `admin_ingest.py` +
`POST /admin/upload` calls `run_confidence_check` and surfaces the verdict
(Approved / Manual review / Rejected / **Scoring didn't run**) on a live
admin screen, with manual approve/reject for borderline cases. Extraction
itself still does not consult it — that remains unbuilt (#18).

**The same paper gets different verdicts.** `paper1` was scored 11 times:

```
 5,  5,  5, 37, 58, 59, 63, 65, 67, 80, 80
```

Against thresholds of 60 (review) and 75 (approve), that spans REJECTED
through APPROVED. `temperature` is 0.1 with no seed, and the per-criterion
score is `max(scores)` across chunks — not the average the commit message
for `0c95f06` claims — so one favourable chunk can carry a paper.

**An infrastructure failure is recorded as an editorial verdict.** When the
Ollama call fails or its JSON will not parse, `_fallback_criteria()` returns
all four LLM-scored criteria at 0 — 85 of the available points — and the
paper is written to `confidence_logs/rejected/` as REJECTED with
justification "Model evaluation failed". Three of `paper1`'s six rejections
scored exactly 5, which is this. A rejection for an unreachable model is
indistinguishable from a rejection on merit.

**Update, 2026-10-05: the dominant real cause of this was found and fixed,
and it was not what it first looked like.** `MODEL_RESPONSE_TOKEN_BUDGET`
was 256 — too few for the model to emit a complete 4-criterion JSON object
with justifications, so every real attempt was truncated mid-object,
`parse_model_response` returned `None`, and the paper fell into the
all-zero fallback above. This had previously been reported (in this doc's
earlier text and to the team) as Ollama being unreachable — that was wrong.
Measured: 256 tokens → 876 chars, parse failed; `MODEL_RESPONSE_TOKEN_BUDGET
= 1024` → 1561 chars, parse succeeds, all 4 criteria score for real. Several
of `paper1`'s 5/5/5 scores recorded above are this truncation bug, not an
Ollama outage and not a genuine low-confidence verdict.

Separately, `admin_ingest.py`'s `decide()` already checks
`evaluated_by == "fallback"` before trusting a verdict, so the admin UI
built on 2026-10-05 does not show a scoring failure as a merit-based
rejection. **Still open:** `run_confidence_check()` itself unconditionally
writes to `rejection_logs/` and `review_queue.csv` as a side effect before
`admin_ingest.py` sees the result, so the on-disk audit trail can still
misrecord a scoring failure as `"outcome": "REJECTED"` with no trace of the
underlying failure — confirmed not hypothetical, see
`rejection_logs/20261005_100226_rejection_from_browser.json`.

Evidence is in `confidence_logs/` on the `main` branch.

**It has never been run on the papers in the graph.** Logs exist only for
`paper1`, `paper2`, `paper` and `IndigenousWomen-led---Garo`. The three garo
papers the 45 triples come from were never scored by it.

**Update, 2026-10-05:** post-token-budget-fix, `garo_1.pdf` was scored for
the first time and came back **83/100 APPROVED** (~4 minutes for 9 pages) —
a one-off verification run, not a formal re-scoring of all three graph
papers, so this line is still technically true for `garo_2`/`garo_3`.

## 10. The access check does not exist

One of the two commitments made to the supervisor was that research papers
pass an access check before extraction. There is no code for it.

The confidence framework's "Ethical Source Handling (ICAT)" criterion is
sometimes mistaken for this. It is not. It scores whether **the paper's own
authors** documented informed consent from **their** research participants.
It says nothing about whether this project is licensed or permitted to use
the paper. There is no licence, copyright, embargo or paywall check anywhere
in the codebase.

What that check should test needs agreeing before it is built.

## 11. No pipeline exists for human-generated data

The second commitment was that workshop transcripts and focus-group data go
through the local model only, never an external one.

No such data has been through the system and no pipeline for it exists. The
only match for "focus group" in the codebase is a keyword in
`Extraction_Check.py` used to *reject* methodology triples — the opposite of
an ingestion path.

The admin upload screen is the natural place for this, and it has no concept
of a data class: a workshop transcript dropped into it would follow exactly
the same route as a paper. Give it a data class, with human-generated data
hard-pinned to the local model, before accepting any.

## 12. LLM locality is enforced, with two files outside the guard

`llm_endpoint.resolve_llm_endpoint()` refuses an endpoint outside our own
network, and `kg_extractor.py`, `rag.py` (both call sites),
`confidence_framework.py` and `pruner/llm_judge.py` all route through it.
`ALLOW_EXTERNAL_LLM=1` overrides it, deliberately and visibly.

Not covered:

- `kg_filter.py` builds its own hardcoded Ollama URL. Imported by nothing,
  so it is inert, but it duplicates three of the verification gates and
  would bypass the guard if ever wired up.
- `script.py` resolves `OLLAMA_URL` from the environment without validation.

Both are teammates' files on `main` and were left alone rather than edited.

`pruner/llm_judge.py` also ships OpenAI and Anthropic judge backends that
reach those providers through their SDKs, so there is no URL to inspect.
Both now refuse via `require_external_llm_opt_in()` before the SDK is
imported. `LLM_JUDGE_BACKEND` defaults to `none`.

**Update, 2026-10-05:** the guard now also carries one deliberate, narrow
exception — `TRUSTED_LLM_HOST` pins exactly one external hostname (the
Tailscale Funnel address that lets the hosted API reach the team laptop's
Ollama) by exact match only, no substring/suffix match. This is still local
inference under the project's data-privacy commitment, just reached over a
tunnel instead of a local network — see `HOSTING.md`. It is not a loosening
of the guard against third-party providers.

## 13. Credentials have been committed, three times

| Where | Instance | Status |
|---|---|---|
| `.env` on `origin/main` HEAD | `cf02815e` | tracked; instance deleted |
| `.env.example` (until 2026-10-04) | `0a31f83f` | real password in an example file; instance deleted |
| local `.env` | `f1d6db66` | gitignored; instance deleted |

All three AuraDB instances fail DNS resolution, so the leaked values are
dead. The exposure is a process finding rather than a live incident, and the
history was not rewritten — a coordinated `git filter-repo` across the team
was judged riskier than the dead credentials warranted.

`.env.example` now holds placeholders. `.env` is still tracked on `main` and
should be `git rm --cached`'d when `main` and `dev` are reconciled.

Any account the system depends on should be owned by the shared team
account, not a personal one, so access outlives the handover.

**Update, 2026-10-05:** the live production AuraDB instance currently in use
(the one holding the 45 real triples, `*.databases.neo4j.io` referenced in
`.env`) is a separate, newly-provisioned instance, not one of the three dead
ones above.

## 14. `main` and `dev` have diverged in both directions

As measured 2026-10-04: `origin/dev` was 56 commits ahead of `origin/main`;
`origin/main` was 41 commits ahead of `origin/dev`. 269 files differ.
**Neither branch was the whole system.**

- `dev` has `verification/`, the full test suite, `prompts/`,
  `subject_specificity.py`, the Flutter i18n work.
- `main` has the confidence framework (as `confidence_framework_update.py`),
  the GitHub Actions workflow, `rejection_logs/`, the SCRUM review notes,
  `auditExtract/`, `run_confidence_batch.py`.

`dev` is the working branch. Anyone cloning the default branch gets the
pre-harness pipeline with no verification gates. Reconciling this is the
first post-demo handover task.

**Update, 2026-10-07:** `origin/dev` was fast-forwarded to pick up the
week's full demo-prep branch (`origin/marcus-extraction-gates`, 23 commits:
gates/retrieval fixes, admin paper-admission, the confidence-framework
token-budget fix, mock accounts, hosting/tunnel infra, answer-synthesis
reliability) — confirmed 0 ahead/0 behind both directions at that point.
Divergence from `main` has since widened as a result, not narrowed:
`origin/dev` is now **88 commits ahead** of `origin/main` (`origin/main` is
still 41 ahead of `dev`). `main` itself has not been touched by this
project's work — reconciling it remains the deferred task, now a larger
one, and is explicitly a post-demo item.

## 15. Response verification and feedback are on unmerged branches

**Resolved, 2026-10-04:** `origin/sangeetha-response-verification` and
`origin/sangeetha-feedback` were merged into `dev` (`8124a6f`) by their
author. `main.py` and `verification/` were untouched by the merge — the
gates are intact — and `app_localizations.dart` survived, so the language
feature was not dropped. Zero file overlap with the gates work at merge
time, no conflicts.

The `chat_service.dart` sources line described below was fixed as part of
that same merge, pointed at `payload['triples']` (the full `SourceEvidence`
list) rather than the old, removed `payload['sources']` key. The
expandable "View verified sources" panel now works end to end, verified
live multiple times since (see #22 for its citation-count-over-shown-answer
follow-up fix).

Original text, kept for the record: `origin/sangeetha-response-verification`
and `origin/sangeetha-feedback` held the expandable-sources UI and the
feedback UI, neither yet in `dev`, and `dev`'s own `chat_service.dart` had
the sources line commented out (`//sources:
_readSources(payload['sources'])`) even though the backend already returned
the data.

## 16. CI does not run the tests

`.github/workflows/extraction-pipeline.yml` triggers only on the
`github-actions` and `complete` branches. It `py_compile`s `script.py` and
lists files. It has never run the 177-test suite, on any branch.

## 17. Only the unit tests are automated

As measured 2026-10-04: 177 tests, all in-process. **Update, 2026-10-07: now
298 tests**, still all in-process — the count has grown steadily with each
fix in this document, but the shape of the gap is unchanged. Not one crosses
a boundary: nothing exercises `add_triples` against a real database, the
HTTP API, or extraction into storage.

`smoke_test.py` covers those seams and is the command to run before
believing the system works. It reports PASS/FAIL/SKIP per stage, and a SKIP
means that infrastructure is not up — not that it passed.

```bash
python smoke_test.py --api http://127.0.0.1:8000
```

**Still unverified end-to-end, as of 2026-10-07:** the admin upload →
confidence-scoring → approve/reject round trip. The 2026-10-07 full demo dry
run deliberately left this read-only (uploading a real PDF triggers a real
~4-minute scoring run) and judged re-verifying it low-value for the time
cost that day — it was last exercised for real on 2026-10-05, before this
week's later retrieval and synthesis changes.

## 18. Auto-extraction from the admin upload is designed, not built

The admin upload screen runs the confidence check and stores or queues the
paper. It does not start extraction.

Extraction is 157.3 seconds per chunk, measured on two mid-document chunks
of garo_2 (183.4 s and 131.2 s). That makes a 22-page paper 2.2 hours, and
all seven papers in `papers/` 10.8 hours. Free hosting has no GPU.

Auto-extraction needs a worker process, a job queue, progress reporting the
admin can watch, and an inference budget. That is a subsystem, not a
feature.

## 19. Hosted answers read poorly, and worse than first assumed

**Fixed, 2026-10-07.** The template dict described below was replaced with
one template per predicate actually present in the production graph (32,
enumerated directly from `data/production_graph/`), each built from a
shared subject/object/plural-agreement shape instead of naive
concatenation. `_humanize_entity` no longer collapses `"Garo"` to "the Garo
people" when it is the grammatical object, which was the direct cause of
the self-referential "The Garo people language used The Garo people."
reported below. Verified two ways: every one of the 45 real production
triples now renders as correct English when run through `_format_triple`
directly, and the live hosted API (tunnel off, the actual failure
condition) was hit with the user's exact reported question and returned
grammatical sentences. 13 new tests, including one that fails loudly the
moment a future paper introduces a predicate with no dedicated template —
see `tests/test_fallback_answer.py`.

**Honest scope limit, unchanged by the fix:** this covers the 32 predicates
that exist today. It does not close limitation #5 (unbounded predicate
vocabulary) — a future paper's new predicate still falls through to the
generic, now plural-aware, word-segmentation path rather than a
hand-written template. Closing that gap for good still needs a controlled
predicate vocabulary at extraction time.

Original text and measurement, kept for the record:

The hosted deployment runs with no LLM. `rag.py`'s `_fallback_answer` builds
an answer from per-predicate templates.

**Measured 2026-10-04: none of them fire.** `_format_triple` defines eight
templates — `IS_A`, `TYPE`, `LOCATED_IN`, `LIVE_IN`, `SPEAK_LANGUAGE`,
`BELONG_TO`, `HAS_LANGUAGE`, `HAS_A_POPULATION`. The graph contains **32
predicates and not one of them is on that list**, so every answer falls
through to `_humanize_predicate`, which only lowercases and strips
underscores.

A real response, taken from the running API over the 45-triple corpus with
no LLM reachable:

> Based on the available knowledge, Population Census 2022 population
> 1,650,159. Garo People bilingual Bengali. Garo People bilingual Garo
> Language. Traditional Garo Houses have property Bamboo floor.

That is not prose. It is the triples with their underscores removed.

This is the same defect as the retrieval scoring had — a hardcoded list
written against an imagined graph rather than the real one — and it is
limitation #5 (uncontrolled predicate vocabulary) surfacing in the answer
layer. A controlled vocabulary would fix both at once.

**It also leads with a known-bad fact.** The first triple returned is
`(Population_Census_2022)-[POPULATION]->(1,650,159)`, which is the
all-ethnic-communities figure, not the Garo one. The correct figure (76,846)
was extracted and then rejected by the grounding gate, because its tighter
citation did not restate the subject's words.

Running locally with Ollama reachable gives genuinely fluent answers through
the same code path, selected by `OLLAMA_URL`. Private hosted inference is a
funded decision, not a configuration change.

## 20. The CSV fallback path ranks differently from the graph path

**Fixed, 2026-10-05:** `ConceptRetriever.retrieve` now scores through the
same `question_keywords`/`score_triple` function `Neo4jRAGSkeleton.query`
uses, and its `top_k` default was raised to `DEFAULT_TOP_K` (25) to match.
The length-rewards-verbosity scoring described below is gone. Left as
recorded for the dated measurement; see `rag.py`'s `ConceptRetriever` and
`tests/test_concept_retriever.py`.

`rag.py` had two retrievers and they did not agree.

`Neo4jRAGSkeleton` uses `question_keywords` and `score_triple`, weighting a
match by where it lands, with `DEFAULT_TOP_K = 25`.

`ConceptRetriever` — the CSV-backed path used by `--kg`, which is the
rehearsed fallback for when AuraDB is unavailable — had its own independent
ranking, still defaulted to `top_k = 10`, and by its own docstring scored on
"length of the `sentence_ref` (longer = more context)".

**That rewarded verbose citations**, which is precisely the pathology
`MAX_SENTENCE_REF_CHARS` was added to `grounding_check` to stop on the
extraction side. The fallback you would switch to under pressure on demo
morning was the one with the worse ranking.

## 21. Retrieval keyword matching missed plain morphological variants

Found 2026-10-07, auditing why some on-topic triples were ranked low.
`question_keywords`/`score_triple_weighted` matched keywords as literal
substrings, so a question using "live" did not match the stored predicate
`LIVING_IN`, and "religious" did not match `HAS_TRADITIONAL_RELIGION` (whose
evidence text says "religion"). Neither is a literal substring of the other.

**Fixed:** `_KEYWORD_EQUIVALENTS`, a small curated dict (same pattern as
`_PLURAL_SUBJECT_SUFFIXES` in #19's fix), maps known cases —
`"live" → ("living", "lived", "lives")`, `"religious" → ("religion",
"religions")`. Measured effect on real scores: `LIVING_IN`'s relative score
for "Where do the Garo live?" went from 0.41 (buried below generic noise) to
1.00 (ranked first); `HAS_TRADITIONAL_RELIGION`'s for the religion question
went from 0.34 (below any workable threshold) to 0.62.

**A general shared-prefix stemming heuristic was tried first and rejected
by measurement**, not preference: even a safe threshold still missed
live/living, and a looser one produced real false positives on this exact
corpus — "status" matched "statute", "family" matched "familiar",
"community" matched "communicate" (which would have partly undone the
hub-dominance mitigation in #4, since "Insufficient Communication" is a
real object value here).

**This is a curated list, not a general fix.** It covers the two gaps found
so far. A future paper's vocabulary will surface new ones the same way these
two were found — by noticing a question that should have matched something
and didn't — not automatically.

## 22. The sources panel showed a source count decoupled from what the answer used

Found and fixed 2026-10-07, after the user noticed "View verified sources
(25)" attached to a 4-sentence answer.

**Root cause:** `chat_service.dart` maps the API's `triples` list 1:1 into
the displayed count, but `rag.py`'s `/query` handler returned the full
`DEFAULT_TOP_K = 25` retrieval as `triples`, completely decoupled from
`SYNTHESIS_EVIDENCE_LIMIT` (10, what the model actually saw). The badge was
always near 25 regardless of how short or focused the real answer was.

**Fixed:** `/query` now calls `skeleton.query(question, top_k=SYNTHESIS_EVIDENCE_LIMIT)`,
so sources, evidence text and the synthesis prompt are built from the same
capped list. No change to answer content — the synthesizer already applied
this cap internally; this just stops fetching, then silently discarding, the
other 15. Verified live: the same population question that showed "(25)"
before now shows "View verified sources (10)".

**A more honest per-question relevance threshold was designed, tested
against real scores across 6 questions, and explicitly rejected before
shipping anything** — not because it was hard to implement, but because it
was unsafe. A 50% threshold kept 14-15 of ~25 sources for some questions
(barely better than no filter); a 60% threshold cut two genuinely relevant
religion triples (scores 7.46, 6.88) while keeping an irrelevant one
("Traditional Garo Houses... bamboo floor", 21.69) that only outscored them
because "traditional" happens to appear in both the question and that
unrelated subject's name — a keyword-overlap artifact, not real relevance.
**Root cause, same as #4: `GaroCommunity`'s dominance creates a dense
cluster of generic-but-not-specifically-relevant triples sitting at 50-85%
of the top score for almost every question** — no single fraction separates
"genuinely about this question" from "just mentions Garo" across question
shapes. Not fixable by more keyword-matching work; needs entity resolution
(#4) first. The sources panel stays at the safe fixed cap (10) rather than
a deeper per-question filter, by deliberate choice, not oversight.

## 23. The synthesizer sometimes invents connections between real, unrelated facts

Found 2026-10-07 on "What are the traditional religious beliefs of the
Garo?" (thin real evidence retrieved): the model wrote confident-sounding
prose inventing links between genuinely unrelated real facts — "bamboo
floors... suggests their religious practices may involve rituals",
"bilingual... could indicate religious practices may be influenced by both
languages." Neither claim exists in any evidence. This is a subtler failure
than inventing a fact outright: it invents a *connection* between two real
facts, and both read as trustworthy prose.

**Not fixed.** Two prompt-only attempts were tried and both failed on live
retesting, then were reverted rather than shipped:

1. An explicit "do not speculate about connections the evidence does not
   state" instruction with forbidden-phrasing examples — the model
   speculated almost identically on rerun.
2. A stronger rewrite with a forbidden-word list, a worked wrong/right
   example, and an instruction to omit off-topic evidence entirely — the
   model made the same connection anyway, only adding a hedge ("although
   this connection is not explicitly stated") instead of omitting it, which
   the instruction had explicitly asked for.

**Working theory, not yet tested:** this is not a wording problem. The
7b-class model at low temperature appears to default to using everything in
its context window rather than selectively omitting weakly-relevant
evidence — plausibly a small-model instruction-following ceiling. The
likely more robust fix is the same lever as #22's deferred relevance
threshold: a deterministic, code-level gate that never hands the model thin
or weakly-matched evidence in the first place, rather than asking it to
self-filter. Both are blocked on the same prerequisite (#4, entity
resolution / hub dominance).

**A related but separate symptom, fixed the same day:** the synthesizer was
also independently padding *on-topic* answers with low-relevance restated
background (85 words / 4 sentences for a question whose real answer is one
word). A sharper prompt — explicit instructions to ignore off-topic
evidence, keep simple answers to 1-2 sentences, and only add the
incomplete-evidence disclaimer when genuinely warranted rather than out of
habit — fixed *this* symptom specifically, tested across 4 real cases
including the demo-critical "Where do the Garo live?" before shipping. **Do
not read this as evidence that #23's speculative-bridging problem is fixable
the same way** — the two prompt attempts aimed at the bridging problem
itself both failed on the same kind of live retest that confirmed this fix
worked. The difference seems to be task shape: "select the relevant evidence
from a mixed pool" responded to clearer instructions; "don't invent a
connection between two genuinely unrelated facts" did not.

**Minor, not chased further:** one test response still mentioned a page
number ("according to information from Page 7...") despite the prompt
explicitly saying not to — the same not-fully-reliable instruction
following, a smaller miss. Not worth another round of live testing unless it
recurs noticeably.

## 24. One extraction has a single-letter subject from a truncated sentence

Found 2026-10-07 during the RAG answer-quality audit, not yet fixed or
reported elsewhere. `garo_3_kg_refined.csv` row 75:
`(E)-[INCLUDES]->(Songsareks)`, citing "e, including Songsareks, likes Hindi
movies" — the extractor's own passage comment records the intended fact as
`(GaroCommunity)-[INCLUDES]->(Songsareks)`, so the sentence genuinely once
began with something like "The Garo community, including Songsareks, likes
Hindi movies" and lost its first word to whatever upstream chunking or
page-text extraction produced `sentence_ref`. The single-letter subject
"E" passed every gate because it is a real, well-formed, verbatim-quoted
token — none of the three gates evaluate whether a subject is a meaningful
noun. Same general class of gap as the declined predicate-fit gate: a gate
can confirm a quote is genuine without confirming the triple built from it
makes sense.
