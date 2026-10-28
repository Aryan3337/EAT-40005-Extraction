# Backlog — feature work deferred out of the Nectar migration

Work that was scoped during the 2026-10-26 design session and then
**deliberately removed from `NECTAR_IMPLEMENTATION_PLAN.md`**.

None of it is migration. None of it has ever worked on any deployment —
Render included. It was bundled into the migration plan at first, which made a
day-and-a-half deployment look like a fortnight of risk. It is real work and
worth doing; it is not worth blocking the deployment or the handover on.

**No deadline.** Pick items up when the migration and handover are safe. Two
tracks, independent of each other and of the deployment:

```
E1 ──> E2 ──> E3 ──> E4 ──> E5     needs a running instance (M2)
G1 ──> G2                           needs nothing
G3 ──> G4                           needs nothing
T1..T5                              translation; T1 needs only a Bangla speaker
```

**G1 is the highest-value code item here** and the best thing to hand to anyone
with spare capacity: it needs no instance access and is about a day and a half.
**T1 is higher value still and is not code at all** -- half a day of a Bangla
speaker's time, reviewing output nobody has yet confirmed is good.

Track T was added on 2026-10-28 and breaks the "none of it has ever worked"
rule above: most of it shipped that day and is live. It is listed here so the
remainder is findable and so nobody repeats the engine measurements.

Sizes are rough person-days for someone who knows this repo.

---

# Track E — Extraction hosted and wired to the admin UI

**DONE 2026-10-28**, on branch `marcus/admin-extraction` (5 commits, pushed,
**not merged to dev**). The live instance is running it. The blocks below are
kept as written because they are still the right design for a *durable*
version; what was actually built is the cheaper in-process variant described
under "What was built instead".

**Do not start E1-E5 as written.** Read this section first.

## What was built instead, and why

The 4.5-day estimate was driven almost entirely by one constraint: the API
image had no spaCy, so `main.py` could not run there, which forced a separate
container, which forced a cross-container job queue with atomic claims. That
constraint died with Render -- `requirements-serve.txt` excluded spaCy because
"a free-tier host's build minutes should not pay for it", and Nectar builds on
our own box. spaCy turned out to be the *only* missing dependency; rapidfuzz
and openpyxl are named in the same comment but are not in `main.py`'s import
closure.

So the API image gained spaCy and the extraction modules, and runs `main.py`
as a **subprocess** -- not an import, because `main.py` builds its
ArgumentParser and parses `sys.argv` at module level, so importing it would
extract using the API's own argv.

What exists now:

- `extract_jobs.py` -- `start/finish/fail/state_for/reap_stale/run_extraction/
  begin`. State goes in the **existing append-only `queue.jsonl`**, because
  `current_queue` already collapses it to one row per paper with later entries
  winning and `/admin/queue` is already polled by the admin page. No new store,
  no new route.
- `POST /admin/extract`, gated on `_admin_authorised()`, refusing anything not
  `ready_to_extract`.
- An automatic trigger on **both** paths a paper can become approved, through
  one shared function.
- One run at a time, second caller refused with **409** rather than queued.
- A **startup reaper** failing runs a restart abandoned (3h), without which one
  restart wedges a paper forever and the one-at-a-time rule then refuses every
  later paper.
- `neo4j_loader/rollback.py`, so a load can be undone by the `run_id`
  `add_triples` has always stamped on it.

Borrowed from E2/E3 below: the stale-job reaping and the one-at-a-time rule.
Deliberately **not** borrowed: the separate image, atomic `os.rename` claims
and the multi-worker test matrix, which solve a multi-worker problem that does
not exist with one process.

## The result that matters more than the wiring

One real run (see `KNOWN_LIMITATIONS.md` §18 for the full measurement):
approved 83/100, auto-extracted, **73 minutes, 98 raw triples, 1 survived the
gates** -- and that survivor was the author's byline scraped off the title
page. Rolled back the same day.

**This invalidates the constraint stated below** that "once a paper is
approved, its gated triples load straight to Neo4j with no triple-level review
step". That assumed the gates' survivors could be trusted unattended. On the
only evidence there is, they cannot. Until the extraction step improves,
approving a paper costs 73 minutes of a box shared with the chatbot and
returns roughly one triple that still needs a human.

**The number worth improving is per-paper yield, not per-chunk speed.**
Measured speed is fine: ~91 s/chunk warm (70/112/92), 178 s for the first
chunk because it loads the 5 GB model, so `garo_2.pdf`'s 50 chunks are ~76
minutes. That is *faster* than the 157.3 s/chunk quoted from a dev machine.

**Known gap in what was built:** `run_extraction` captures the subprocess
output and writes `uploads/logs/<paper>.log` only once it exits, so there is
no progress visible during a 73-minute run. Streaming it is the obvious next
improvement.

---

## Original design, retained for reference

**~4.5 days.** Blocked on a running instance (`NECTAR_IMPLEMENTATION_PLAN.md`
M2).

## Why this is wanted

`flutter_application/lib/features/admin/admin_page.dart:275`:

```dart
void _notYetWired(String paper) {
  // Honest about being a placeholder. A button that looks real and silently
  // does nothing would have the admin believe extraction had started.
  ...  'Extraction is not wired up yet. $paper is queued ready for it; '
       'run it from the CLI for now.',
```

The admin UI admits papers, scores them with the confidence framework, routes
them to accept / manual-review / reject, and labels the accepted ones "Waiting
for extraction". Nothing acts on that label. `/admin/review` is manual
accept/reject of the *paper*, not of extracted triples.

## What already exists

**`main.py` does the whole job.** Its own description: "Extract a paper into
triples, gate them, and upload to Neo4j". Signature:
`main.py <pdf_path> [model] [--dry-run] [--no-gates]`. The three gates
(well-formedness, grounding, quote-genuineness) are deterministic, LLM-free and
cost about a second per few hundred rows. Subject-specificity correction is
documented as "Fully automatic, no manual review step."

So this track does not build extraction. It makes an existing pipeline
reachable from a button.

## Two constraints that shape every block below

**The human gate stays at paper admission.** Once a paper is approved, its
gated triples load straight to Neo4j with no triple-level review step. That is
a deliberate decision — see `NECTAR_MIGRATION.md`. It means the three gates are
load-bearing in a way they were not when a human eyeballed CSVs before
loading. **No block here may add a `--no-gates` path.**

**Extraction takes ~1.2 hours per paper** (`load_production_graph.py`'s header
explains that this is exactly why it exists as a separate script). Every design
choice below follows from that number.

## E1 — The `extract` service

**Blocks:** E2 · **Size:** 0.5 day

A fourth compose service built from the repo's existing root `Dockerfile`
(`python:3.11-slim` + `requirements.txt` + `spacy en_core_web_sm`, no torch, so
it stays small). Give it:

- `OLLAMA_URL=http://ollama:11434/api/generate` and the `NEO4J_*` values from
  `.env` — it writes to the graph directly
- `/mnt/data/uploads:/app/uploads` and `/mnt/data/extract:/app/output`, so it
  reads the papers the API stored and its output survives a rebuild
- `OLLAMA_MODEL` left alone: `main.py` defaults to `deepseek-r1:7b`, which the
  chatbot does not use. Pull it —
  `docker compose exec ollama ollama pull deepseek-r1:7b` — and note this is
  the second ~4.7 GB model, which is why the volume is 20 GiB.

Extraction and chat share one Ollama on 16 CPU-only vCPUs, so a batch run makes
the chatbot crawl. Accepted: extraction is a deliberate, attended activity. Say
so in the runbook.

**Done when:** `docker compose exec extract python main.py --dry-run <a-pdf>`
completes and writes a `_kg_refined.csv` to `/mnt/data/extract/`.

## E2 — Job protocol on the shared volume

**Blocked by:** E1 · **Blocks:** E3 · **Size:** 1 day

The API container cannot run `main.py` — its image has no spacy, by design
(`requirements-serve.txt` excludes it deliberately, with a comment explaining
why). It also must not be given the Docker socket to start containers: that is
root-equivalent on the host and would be the worst single thing in the
handover.

So the API **enqueues** and the `extract` service **executes**. A directory on
the shared volume is the queue.

**Create `extract_jobs.py`**, importable by both containers — add it to
`Dockerfile.serve`'s `COPY`; the root `Dockerfile` copies everything already:

- `enqueue(paper, *, jobs_dir) -> str` — writes `<jobs_dir>/<job_id>.json` with
  `{job_id, paper, state: "queued", enqueued_at}`, returns the id
- `claim_next(jobs_dir) -> dict | None` — atomically moves a `queued` job to
  `running` with `os.rename` (atomic within one filesystem), so two workers
  cannot take the same job
- `update(job_id, *, state, jobs_dir, **fields)` — writes `running`, `done` or
  `failed`, plus `triples_loaded`, `error`, timestamps
- `status_for(paper, jobs_dir) -> dict | None` — what the UI polls

States are `queued → running → done | failed`. Nothing else.

**Test** (`tests/test_extract_jobs.py`) with `tmp_path`, no containers needed:
enqueue then claim returns that job; a second `claim_next` returns `None`;
concurrent claims yield exactly one winner; a `failed` job records its error;
`status_for` an unknown paper returns `None`.

## E3 — The worker loop

**Blocked by:** E2 · **Blocks:** E4 · **Size:** 1 day

**Create `extract_worker.py`** as the `extract` service's `command:`. A loop
that calls `claim_next` and, on a claim, runs `main.py` as a subprocess against
the claimed paper, streaming output to a per-job log on the volume, then marks
`done` or `failed` with the triple count.

Specifics that matter:

- **Poll on a sleep, not a filesystem watcher.** A 5s sleep is fine for a
  1.2-hour job and keeps this readable for a successor.
- **One job at a time.** Two concurrent 1.2-hour extractions against a shared
  Ollama is worse than a queue.
- **Never pass `--no-gates`.** See the constraints above.
- **`main.py` already writes a checkpoint CSV of raw model output before any
  filter can fail**, so a crash at minute 50 does not lose the LLM time.
  Surface the checkpoint path in the job record so that is actionable rather
  than merely true.
- **Reap stale jobs on startup:** mark any `running` job older than ~3 hours as
  `failed`, or a container restart mid-job blocks the queue forever.

**Test** (`tests/test_extract_worker.py`) with the subprocess call injected, so
the loop is testable without a real 1.2-hour run: a queued job lands `done`; a
non-zero exit lands `failed` with stderr captured; an empty queue is a no-op; a
stale `running` job is reaped.

## E4 — `POST /admin/extract`

**Blocked by:** E3 · **Blocks:** E5 · **Size:** 1 day

In `rag.py`'s `do_POST`, beside `/admin/upload` and `/admin/review` (~line
2383):

- Gate on `self._admin_authorised()`, exactly as the other admin routes do
- Reject unless the paper exists in `uploads/` **and** its queue decision is
  approved — a rejected or manual-review paper must not be extractable
- Call `extract_jobs.enqueue`, return `202` with the `job_id`
- Extend `/admin/queue` so each entry carries its job state. The Flutter admin
  page already polls that endpoint, so no new polling route is needed.

**Test** (`tests/test_admin_extract.py`, following `tests/test_admin_ingest.py`'s
shape): no secret → 403; unknown paper → 404; a paper pending manual review →
409; an approved paper → 202 and a job appears; `/admin/queue` reflects state.

## E5 — Wire up the Flutter button

**Blocked by:** E4 · **Size:** 1 day

Replace `_notYetWired` with a real `POST /admin/extract` through
`flutter_application/lib/services/admin_service.dart` (follow `uploadPaper` at
~line 186), and surface the job state in the queue list, which already polls.

**Keep that placeholder comment's spirit.** A 1.2-hour job must look like a
1.2-hour job: show `queued` / `running since <time>` / `done — N triples
loaded` / `failed — <reason>`, never a spinner implying it is nearly finished.
Update the "Waiting for extraction" label (~line 528) once something acts on
it.

**Done when** an admin can upload a PDF, see it scored, approve it, press
Extract, close the browser, return an hour later to a triple count — and those
triples are in AuraDB.

---

# Track G — Graph quality and retrieval

**~5.5 days. Needs no instance, no credentials, no deployment.** This is the
track to delegate to anyone without dashboard access.

Both branches touch retrieval code that **Render also serves until
`NECTAR_IMPLEMENTATION_PLAN.md` M3 lands**. Own branch, own PR, baseline proven
at each step. Current baseline, re-measured 2026-10-27: **473 pass / 9 fail /
0 collection errors** (the 9 are all `tests/test_rag_languages.py`,
pre-existing). Run it as `python -m pytest tests/ -q`.

This replaces the **451 / 9 / 2** figure recorded when this file was written,
which was not a measurement: `test_auth_store.py`'s collection error aborted
collection for the whole suite, so that command ran **zero tests** and exited
1. Fixed 2026-10-27 — the file had been asserting a registration feature
reverted on 15 Oct. `test_insert.py` no longer errors either; it does not need
live Neo4j.

## G1 — Port the topic filter to the graph path

**DONE 2026-10-28.** Landed as `rag.topic_focused`, shared by both retrieval
paths, plus the `score > 0` cut. `tools/compare_retrieval_paths.py` reports
**off-topic 27 → 0** with the `csv` column unchanged and `score 0` still 0.
Tests in `tests/test_graph_topic_filter.py` (8, all three steps below).

**One thing this does NOT establish.** The measurement is offline, over the
112-triple CSV corpus, and it proves the junk is gone from the evidence
block. Whether the gate now *answers* "What is the Garo population?" instead
of refusing it needs the eight questions re-run against the deployed
instance, which needs an API rebuild. Until then KNOWN_LIMITATIONS 27 stays
open, narrowed to that one unverified sentence. **G2 is unblocked.**

The original entry follows, because its measurements are the before-figures.

**Blocks:** G2 · **Size:** 1–1.5 days · **Highest-value item in this file**

`Neo4jRAGSkeleton.query` lacks two filters that `ConceptRetriever.retrieve`
applies. Measured over the same 112 triples, so the comparison isolates
algorithm from data, at the `top_k` the API actually uses
(`SYNTHESIS_EVIDENCE_LIMIT = 10`, passed at `rag.py:2434`): the graph path
returns **27 off-topic triples across 8 representative questions**.

```
question                                       graph  csv  off-topic
What languages do the Garo speak?                 10   10          4
What is the traditional religion of the Garo?     10   10          4
Where do the Garo live?                           10    4          8
What medicinal plants are used?                   10   10          0
How has Garo livelihood changed?                  10    8          2
What is the Garo population?                      10    1          9
Tell me about matrilineal inheritance              5    5          0
What happens during antepartum care?               1    1          0
                                              TOTAL              27
```

Reproduce with `python tools/compare_retrieval_paths.py`.

The counts matter less than what the triples are. **Asked for the traditional
religion of the Garo, the four highest-scoring pieces of evidence handed to
synthesis are about language and residence:**

```
score 8.49  (Garo_People)   -[BILINGUAL]->               (Garo_Language)
score 8.49  (GaroCommunity) -[LANGUAGE_USED]->           (Garo)
score 8.49  (GaroCommunity) -[HAS_LANGUAGE_Maintenance]-> (GaroLanguage)
score 8.49  (GaroCommunity) -[RESIDENTS]->               (GaroHills_Meghalaya)
```

They tie at 8.49, so **ranking cannot separate them from correct evidence —
only a topic filter can.** The population question is the worst case: 9 of 10
returned triples are off-topic, where the CSV path correctly returns 1.
"Where do the Garo live?" returns language triples; the location triples it
*should* return (`HAS_LOCATION -> Telki/Jolui/Kakraid`) score 4.73, below the
language noise at 8.28.

`matches_topic` also *promotes* real evidence, because removing noise frees
slots in `top_k`.

**Note on an earlier figure:** this was first reported as 11 off-topic triples.
That was measured at `top_k=6`, which is not what the API passes. At the real
value of 10 it is 27. The harness now defaults to importing
`SYNTHESIS_EVIDENCE_LIMIT` so it cannot drift from production again.

1. Extract `matches_topic` from its closure inside `ConceptRetriever.retrieve`
   to module level in `rag.py`. **Pure refactor** — the baseline above must be
   unchanged. Any movement means the extraction was not pure.
2. Call it in `Neo4jRAGSkeleton.query` after the sort, before
   `dedupe_triples(...)[:top_k]`. **Preserve the CSV path's fallback:** if
   nothing survives, keep the unfiltered list, or questions with no topical
   match return nothing at all.
3. Add the `score > 0` cut in the same place. It had **zero** observed effect on
   those 8 questions — keep it anyway, because Cypher's `WHERE` matches over
   `passage`, which is not in `rag._FIELD_WEIGHTS`, and does not strip the
   `live`/`livelihood` false positive that `_keyword_matches` does. **Do not
   claim it as a measured win.**

Two things to know going in: `matches_topic` reads a `question` field the Cypher
`RETURN` does not select (harmless today — no community data is loaded; comment
it at the Cypher rather than silently extending the query), and `topic_forms` is
a hardcoded two-entry dict (`languages`, `speak`), so porting carries that
hardcoding onto the graph path. **Do not generalise it here** — separate work,
its own recall risk, listed below.

**Test** in `tests/test_rag_retrieval.py`, feeding rows to the skeleton directly
with no live driver. Regression-test both measured cases: the `RESIDENTS` triple
on a language question, and the population question returning one triple.

Re-run `python tools/compare_retrieval_paths.py` when done: **off-topic must
reach 0** without the `csv` column dropping.

**What the three steps became (2026-10-28).** Step 1's extraction was not
kept pure in the end -- it was pure as a refactor, verified by the baseline
staying at 27, and then the graph path's call changed the figure to 0. Step
2's fallback is preserved: `topic_focused` returns its input unchanged when
nothing matches, and a test asserts it. Step 3 went in as specified and is
still not claimed as a win, but it is no longer unexercised -- two tests
cover the two cases the rationale named, a `question`-only match and a
`passage`-only match, both of which score 0 while satisfying the Cypher or
the filter. The `question` field is commented at the Cypher as asked, not
added to the RETURN. Tests went in a new `tests/test_graph_topic_filter.py`
rather than `tests/test_rag_retrieval.py`: that file tests pure scoring
helpers and has no driver scaffolding, and the filter's story is long enough
to want its own docstring. `--top-k` overrides the default if
`SYNTHESIS_EVIDENCE_LIMIT` ever changes; `--question` checks a single case.

## G2 — Guarded two-hop expansion

**Blocked by:** G1 · **Size:** 2 days

**Read this before starting: the graph currently has no multi-hop structure to
traverse.** Measured over the 112-triple export:

| | as-is | after merging the 3 obvious name groups |
|---|---|---|
| entities | 159 | 153 |
| degree-1 leaves | 139 (87%) | 134 (**88%**) |
| connected components | 49 | **45** |
| largest component | 27 entities (17%) | 30 (20%) |

**Re-measured against live AuraDB 2026-10-27.** This paragraph used to say
AuraDB was worse-shaped than the CSV corpus, with `GaroCommunity` carrying 434
of its 715 relationships. That is no longer the case, because the graph was
cleaned. The live shape now essentially *is* the CSV shape:

| | CSV corpus | live AuraDB, 2026-10-27 |
|---|---|---|
| entities | 159 | 181 (159 connected + 22 isolated) |
| degree-1 leaves | 139 (87%) | 139 |
| `GaroCommunity` degree | 13 | 25 |

So the table above applies to the deployed graph too, and the argument for
building two-hop expansion **guarded** is unchanged — it rests on 87% of
entities being leaves, which both corpora agree on. The 22 isolated entities
carry no `Entity`->`Entity` relationship at all and are unreachable by any
traversal, single- or multi-hop.

Every retrieval `MATCH` in the codebase is single-hop today.

Unguarded two-hop expansion therefore either finds nothing new — starting from a
leaf, 88% of the time — or dumps a hub's whole neighbourhood into the evidence
window, which is exactly the noise G1 just removed. So build it **guarded**, and
expect it to rarely fire on today's corpus:

- Expand to two hops only when single-hop results are thin, below a threshold
- **Never traverse through a node whose degree exceeds a cap.** This is the
  whole guard. Without it, this block makes retrieval worse
- Second-hop triples must still pass `matches_topic` from G1
- Rank expanded triples below single-hop ones — they are weaker evidence

Either add a `--kg`-mode equivalent or explicitly document that traversal is
graph-path-only, so the CSV fallback's behaviour stays predictable.

**Test** on a synthetic graph of known shape — a hub, a chain, an isolated pair
— so the guard is provable without a live database: a thin single-hop result
expands along the chain; expansion refuses to cross the hub; an off-topic second
hop is dropped; a rich single-hop result does not expand.

**Report the negative result.** If traversal fires on 0 of the 8 benchmark
questions, that is a finding for `docs/ICSE_SEIS_EVIDENCE_REPORT.md`, not a
failure. "Graph-aware retrieval is implemented and the corpus is too sparse to
exercise it" is considerably more defensible than silence about either half.

## G3 — Entity canonicalisation at load time

**Blocks:** G4 · **Size:** 1–1.5 days

The graph holds five spellings of one entity — `Garo`, `GaroCommunity`,
`Garo_People`, `Garo_Community`, `GaroPeople` — plus `GaroLanguage` /
`Garo_Language` and `Mandai_TMPs` / `MandaiTMPs`. Nothing reconciles a new
extraction against entities already in the graph, so every paper mints fresh
near-duplicates.

**Still true after the 2026-10-27 cleanup** — checked directly against the live
instance, which returns all of `Garo`, `GaroCommunity`, `GaroPeople`,
`Garo_People`, `Garo_Community`, `GaroLanguage` and `Garo_Language`. Cleaning
the unattributed relationships did not canonicalise anything, so this item is
untouched by it.

`neo4j_loader/insert.py:40` is the insertion point: `insert_triple` does
`MERGE (s:Entity {name: $subject})`. Canonicalise the name immediately before
that MERGE and duplicates collapse onto one node for every future load.

Write `canonical_entity_name(name)`: split camelCase and snake_case, lowercase
for *comparison only*, drop filler words (`the`, `of`, `and`, `people`,
`community`), map to one chosen surface form. Keep a display name on the node;
do not destroy the original string.

**Be conservative, and mirror `subject_specificity.py`'s guard style** — that
module exists precisely because an over-eager automatic rewrite is worse than
none. Merging two genuinely different entities is unrecoverable once loaded.

**`Mandi` and `Garo` are the same people**, and appear as unrelated entities, as
do `MandiLanguage` and `GaroLanguage`. String normalisation cannot know that.
Leave it to an explicit alias table seeded by a domain decision — probably
Tanjila's — and **do not infer it**.

**Test** (`tests/test_entity_canonical.py`): the five `Garo` spellings collapse
to one; `GaroHills_Meghalaya` does **not** collapse into `Garo`;
`GaroCommunityHealthStatus` stays separate; `Mandi` and `Garo` stay separate
absent an explicit alias.

Note the measurement in G2: canonicalisation alone takes components from 49 to
45. It is worth doing to stop the fragmentation getting worse, **not** as a
route to a traversable graph. Density comes from more papers, which is Track E.

## G4 — One-off AuraDB merge

**Blocked by:** G3 · **Size:** 0.5 day

G3 fixes new loads; the existing graph still holds the duplicates. Write a
`--dry-run`-first script applying `canonical_entity_name` to live nodes and
merging matches, reusing the `run_id` stamping convention from
`neo4j_loader/insert.py` so the merge is auditable and reversible.

**Export the graph before running it.** This rewrites the production database.
The warning that used to stand here — that the live DB was messier than the CSV
export, 670 of 715 relationships carrying no `run_id` — no longer applies: as
of 2026-10-27 the live graph is exactly the clean 112-triple corpus. That makes
this item *easier*, not unnecessary: the duplicate-entity problem it addresses
(`GaroCommunity` vs `Garo_People` vs `Garo People`) is a property of the corpus
itself, not of the uncleaned leftovers. Re-measure before starting; do not
assume either figure.

**Done when:** `--dry-run` lists exactly the intended merges, a real run reduces
entity count, and a before/after triple count proves nothing was lost.

---

# Also deferred, not yet specified

- **Streaming.** The single highest perceived-quality change available, and it
  belongs in the handover document rather than here — see
  `NECTAR_IMPLEMENTATION_PLAN.md` H4. Every Ollama call sets `"stream": False`
  (`rag.py:405`, `:1585`, `:1713`, `confidence_framework.py:303`) and
  `nginx.conf` sets `proxy_buffering on`, so a 40s answer is 40s of blank
  screen. Three surfaces, no extra compute.
- **Generalising `topic_forms`** beyond its two hardcoded entries (`languages`,
  `speak`), with the recall risk stated explicitly.
- ~~**Cleaning AuraDB's 670 `run_id`-less relationships.**~~ **Done — verified
  2026-10-27, not by this team's planned work.** The live instance now holds
  195 nodes / 124 relationships, of which 112 are `Entity`->`Entity` and all
  112 carry a `run_id` and a `sentence_ref`, matching the CSV export exactly.
  Nothing in this repo records who cleaned it or how, which is worth knowing
  before anyone relies on it staying clean.
- **Concurrency limiting.** `ThreadingHTTPServer` accepts in parallel, one
  Ollama serialises at ~40s each, so the fourth simultaneous question exceeds
  `rag.py`'s 130s timeout and reads as a failure rather than a wait. Accepted
  for now; an explicit limit returning an honest "busy" would be more truthful.

---

# Track T — Translation quality

Added 2026-10-28, and unlike the rest of this file **most of it is already
done and live**. It is here so the remaining items are findable, and so
nobody repeats the measurements. The detail, including every raw example,
is KNOWN_LIMITATIONS 29.

**What changed on 2026-10-28, all deployed:**

| | |
|---|---|
| `5b626e7` | Appended commentary is stripped from every translation, and the prompt tells the model not to produce it. The strip is what works; the prompt alone was measured and does not. |
| `7a251fe` | SCRUM-318's `translation_incomplete` and `restore_numbers`, which only ever ran on the online providers, now run on the deployed one. |
| `998a5eb` | Refusals are served from `_NO_EVIDENCE_MESSAGES` instead of being put through the model. Fixes `मujhe`, and a refusal costs zero generations where it cost two. |
| `07badae` | `translate_local` decodes with beam search, and the sentence splitter stops breaking "T. indica" in half. |
| `2454429` | **The translator is NLLB-200-600M, not `mistral:7b`.** A grounded Bangla answer went from 70-120s to ~22s. |

**T1 — Native-speaker review of the Bangla and Hindi.** *Size: half a day.
Needs no code, no instance access, and it is the highest-value item in this
file.* Every engine judgement on this page, including the decision to deploy
NLLB, was made by reading translations against their English source without
a Bangla speaker. The faults found were gross enough that the reading is not
in doubt; **the rate is not established, and no one has confirmed the current
output is good rather than merely better.** Sit someone who reads Bangla in
front of https://136.186.108.232.sslip.io/ with the eight benchmark
questions. Until this happens, the honest claim is "fit to review", not
"correct".

**T2 — Keep scientific names in Latin script.** *Size: half a day.* NLLB
renders `Justicia adhatoda` as `জাস্টিসিয়া অ্যাড্যাটোডা`, which a reader
cannot look up. `T. indica` and `S. cumini` survive because they are short
and capitalised, so the behaviour is inconsistent as well as lossy. The shape
of the fix is the one already in `local_translation.py`: `_prepare_names`
protects `Garo` and `Mandi` by substitution, and a binomial is a more regular
pattern than either.

**T3 — Spell a proper noun the same way twice.** *Size: unclear, possibly not
worth it.* One answer called the Garo religion `সঙ্গশেরক` in its first
sentence and `স্যাংশারেক` in its second. Per-sentence translation is the
cause: each sentence is a separate generation with no memory of the last.
T2's substitution approach would fix it for known names, which may be all
that matters.

**T4 — The English answer expands abbreviations the evidence did not.**
*Size: half a day to confirm, unknown to fix.* Seen once: synthesis turned
`T. indica` into "Terminalia indica", a different genus from the tamarind the
source means. This is upstream of translation and survives any engine swap,
and it is more serious than the translation faults because the English answer
is what everything else is checked against. Confirm the rate before fixing.

**T5 — One refusal message, not two tables.** *Size: an hour, with G-track
tidying.* `_NO_EVIDENCE_MESSAGES` holds `bn`/`en`/`hi`; the dict inside
`_no_evidence_message` holds `en`/`es`/`fr`/`hi`/`zh`, has **no `bn`**, and
gives Hindi different wording. Nothing reaches the divergence today, but
`_no_evidence_message("bn")` would raise `KeyError`. The nine failing tests
in `tests/test_rag_languages.py` assert against the second table, so retiring
them and collapsing the tables is one job rather than two.

**Not worth doing, and why, so nobody re-runs it:** `m2m100-418M` and
`Helsinki-NLP/opus-mt` were both measured against the same five answers and
are both worse than what is deployed -- opus-mt dangerously so, because it
reads fluently while inverting the source. IndicTrans2 is MIT and
purpose-built for these languages and would be the natural next engine, but
every HuggingFace repo is gated behind an access request.

