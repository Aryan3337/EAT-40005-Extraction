# Known limitations

What this system does not do, with the evidence for each. Written for
whoever inherits the project.

Everything here was measured, not estimated. Where a number appears, the
command that produced it is given so it can be re-checked.

Last updated 2026-10-04.

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

Three separate problems.

**It is not wired to anything.** `grep -rn "confidence_framework\|run_confidence_check" --include=*.py .`
returns nothing outside the module itself. Extraction does not consult it.
Paper admission is a manual step a human performs and records.

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

Evidence is in `confidence_logs/` on the `main` branch.

**It has never been run on the papers in the graph.** Logs exist only for
`paper1`, `paper2`, `paper` and `IndigenousWomen-led---Garo`. The three garo
papers the 45 triples come from were never scored by it.

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

## 14. `main` and `dev` have diverged in both directions

`origin/dev` is 56 commits ahead of `origin/main`; `origin/main` is 41
commits ahead of `origin/dev`. 269 files differ. **Neither branch is the
whole system.**

- `dev` has `verification/`, the full test suite, `prompts/`,
  `subject_specificity.py`, the Flutter i18n work.
- `main` has the confidence framework (as `confidence_framework_update.py`),
  the GitHub Actions workflow, `rejection_logs/`, the SCRUM review notes,
  `auditExtract/`, `run_confidence_batch.py`.

`dev` is the working branch. Anyone cloning the default branch gets the
pre-harness pipeline with no verification gates. Reconciling this is the
first handover task.

## 15. Response verification and feedback are on unmerged branches

`origin/sangeetha-response-verification` and `origin/sangeetha-feedback`
hold the expandable-sources UI and the feedback UI. Neither is in `dev`.

Merging conflicts on eight files including `main.py`, whose version on those
branches predates the verification gates — a careless resolution silently
un-wires all three gates, and no test would catch it, because nothing tests
`main.py` end to end. Those branches also lack `app_localizations.dart`, so
a naive merge drops the language feature.

On `dev` itself, `chat_service.dart` has the sources line commented out:
`//sources: _readSources(payload['sources'])`. The backend already returns
the data.

## 16. CI does not run the tests

`.github/workflows/extraction-pipeline.yml` triggers only on the
`github-actions` and `complete` branches. It `py_compile`s `script.py` and
lists files. It has never run the 177-test suite, on any branch.

## 17. Only the unit tests are automated

177 tests, all in-process. Not one crosses a boundary: nothing exercises
`add_triples` against a real database, the HTTP API, or extraction into
storage.

`smoke_test.py` covers those seams and is the command to run before
believing the system works. It reports PASS/FAIL/SKIP per stage, and a SKIP
means that infrastructure is not up — not that it passed.

```bash
python smoke_test.py --api http://127.0.0.1:8000
```

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

`rag.py` has two retrievers and they do not agree.

`Neo4jRAGSkeleton` uses `question_keywords` and `score_triple`, weighting a
match by where it lands, with `DEFAULT_TOP_K = 25`.

`ConceptRetriever` — the CSV-backed path used by `--kg`, which is the
rehearsed fallback for when AuraDB is unavailable — has its own independent
ranking, still defaults to `top_k = 10`, and by its own docstring scores on
"length of the `sentence_ref` (longer = more context)".

**That rewards verbose citations**, which is precisely the pathology
`MAX_SENTENCE_REF_CHARS` was added to `grounding_check` to stop on the
extraction side. The fallback you would switch to under pressure on demo
morning is the one with the worse ranking.
