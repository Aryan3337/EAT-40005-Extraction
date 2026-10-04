# Knowledge Graph Extraction Backend

Extracts knowledge graph triples from academic PDF papers about the Mandi/Garo community using a local LLM (Ollama + DeepSeek R1 7B) and uploads them into a Neo4j AuraDB database.

## Overview

### Pipeline

```text
PDF Research Paper
        ↓
Text Extraction (pdfplumber)
        ↓
Text Chunking
        ↓
LLM Triple Extraction (Ollama + DeepSeek R1 7B)
        ↓
Deduplication
        ↓
Validation Gate (structure check + research-artifact exclusion)
        ↓
Subject-Specificity Correction (dependency parse, automatic)
        ↓
Verification Gates  ← hard gate, drops anything not provably cited
  1. well-formedness
  2. grounding (+ citation-length bound)
  3. quote-genuineness (verbatim against the source PDF page)
        ↓
Neo4j Upload
        ↓
Knowledge Graph
```

Everything from the validation gate down runs locally and costs nothing: no
LLM call is made after extraction. The verification gates are a hard gate, not
an advisory flag — see [The verification gates in `main.py`](#the-verification-gates-in-mainpy).

---

## Quick Start with Docker (do this — no Python or Ollama install needed)

Follow these steps in order. Every command is copy-paste ready.

### Step 1: Install Docker Desktop

1. Go to https://www.docker.com/products/docker-desktop and download it for your OS.
2. Install it like any normal application, then **open it once**.
3. Wait until the whale icon in your system tray (Windows: bottom-right near the clock; Mac: top menu bar) stops animating. That means Docker is ready.
4. Confirm it's working — open a terminal and run:
```bash
   docker ps
```
   If you see an empty table with column headers (`CONTAINER ID`, `IMAGE`, etc.), you're good. If you see a connection error, Docker Desktop isn't running yet — open it and wait another minute, then try again.

### Step 2: Clone the repo

```bash
git clone <repo-url>
cd EAT-40005-Extraction
```

### Step 3: Set up your `.env` file

Copy the example file:

- **Windows (PowerShell):** `copy .env.example .env`
- **Mac/Linux:** `cp .env.example .env`

Open the new `.env` file in VS Code and fill in the real Neo4j credentials (ask Aidan or another team member if you don't have them):

NEO4J_URI=neo4j+s://your-instance-id.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password-here


**Never commit this file.** It's already excluded via `.gitignore` — don't remove it from there.

### Step 4: Build and start the containers

```bash
docker compose up --build -d
```

This builds the Python environment and starts two containers:
- **`ollama`** — runs the local LLM server
- **`app`** — the extraction pipeline, connected to `ollama` internally

The `-d` flag runs it in the background so you get your terminal back immediately.

### Step 5: Pull the DeepSeek model (first time only)

```bash
docker compose exec ollama ollama pull deepseek-r1:7b
```

This downloads ~4.7GB and can take several minutes depending on your connection. You only need to do this **once per machine** — it's saved in a Docker volume and survives rebuilds. To check what's already downloaded:

```bash
docker compose exec ollama ollama list
```

### Step 6: Add a paper and run extraction

Drop a PDF into the `papers/` folder in the project root (this folder is gitignored — PDFs stay local, they don't get committed). Then run:

```bash
docker compose exec app python main.py papers/your_paper.pdf
```

**What you'll see happen:**
1. Text extraction and chunking progress
2. Per-chunk extraction output (`Chunk 1/50...`, `parsed N triples`)
3. Deduplication summary
4. **`Running validation gate...`** — every triple is checked for structural correctness; invalid ones are individually rejected (not the whole batch), and you'll see a count like `Validation: 12 passed, 3 rejected.`
5. Any **`[FILTERED]`** lines naming triples that matched research-methodology artifacts (interview/participant language) rather than real cultural content — these are **excluded**, not merely warned about
6. A local CSV backup of the full pre-gate set saved to `output/<paper_name>_kg.csv`
7. **`Running verification gates...`** — the three deterministic gates (see below). Expect a steep drop here: on the measured `garo_1` corpus roughly 300 extracted triples come out as 13
8. `output/<paper_name>_kg_refined.csv` (what will be uploaded) and one `output/<paper_name>_kg_<gate>_flags.csv` per gate that rejected anything, each row carrying the reason it was rejected
7. Upload confirmation: `Uploaded N triples to Neo4j.`

**If you see `Validation: 0 passed` or very few triples survive:** this is a known issue, not something you broke. See **Known Issues** below.

### Step 7: Stopping the containers

```bash
docker compose down
```

Your downloaded model and `.env` config are preserved — starting again won't require re-downloading anything.

---

## The verification gates in `main.py`

Since 2026-10-04 `main.py` runs three deterministic, LLM-free gates between
extraction and the Neo4j upload, via `verification/gate.py`:

1. **Well-formedness** (`verification/wellformedness_check.py`) — entity and
   predicate shape; also catches a Subject and Object that restate the same
   concept.
2. **Grounding** (`verification/grounding_check.py`) — every word of the
   Subject and Object must appear in the triple's own `sentence_ref`, and that
   citation must be at most 200 characters, so it is a sentence rather than a
   whole paragraph.
3. **Quote-genuineness** (`verification/quote_check.py`) — the `sentence_ref`
   must be a real, verbatim quote from its own page of the source PDF.

They are a **hard gate**: a flagged triple is dropped, never held for review,
because this graph feeds a fully autonomous chatbot with no human in the loop.
A triple can be flagged by more than one gate, and it is recorded under each —
the flag files are an audit trail, not a first-match-wins dispatch. The whole
pass is free and takes about a second per few hundred rows.

| Flag | Effect |
| --- | --- |
| `--no-gates` | Skip all three and upload whatever clears the older structural checks, as this script did before the gates were wired in |
| `--dry-run` | Do everything except the Neo4j upload; the CSVs are still written |

```bash
python main.py papers/your_paper.pdf --dry-run      # see the numbers, upload nothing
python main.py papers/your_paper.pdf --no-gates     # pre-2026-10-04 behaviour
```

> **On the measured numbers.** The "300 → 13" figures in this README and in the
> results doc were produced with the `extraction_broad_v2` prompt
> (`prompts/extraction_broad_v2.txt`), which the now-removed `main_hardened.py`
> swapped in. `main.py` uses `kg_extractor.py`'s own built-in prompt, so its
> yield will differ. The gates themselves behave identically either way; only
> what they are fed changes. Use `test_extraction_prompt_config.py` to compare
> prompts without touching the production path.

---

## Running the RAG query tool

Once you've got triples in a CSV (from Step 6), you can query them directly without going through Neo4j:

```bash
docker compose exec app python rag.py --kg output/your_paper_kg.csv --query "Where do the Garo people live?" --approach concept
```

Use `--approach concept` (recommended, fast, no LLM needed) rather than `--approach cypher` — the Cypher approach currently has a known issue (see below) and returns empty results.

### Connect the Flutter frontend

Start the RAG HTTP bridge from the extraction project root. To query the triples already uploaded to Neo4j, use:

```bash
python rag.py --neo4j --serve --approach concept
```

The command reads `NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD` from `.env`. Alternatively, use the CSV backup created by the extraction step:

```bash
python rag.py --kg output/your_paper_kg.csv --serve --approach concept
```

The Flutter app sends `POST http://localhost:8000/query` with `{"query":"your question"}`. The bridge returns the formatted triples as `answer` and their source sections as `sources`.

The `answer` field is synthesized from the retrieved graph evidence using the local Ollama model configured by `OLLAMA_MODEL`. If Ollama is unavailable, the API uses a deterministic human-readable summary of the graph facts instead. Raw formatted graph evidence is also returned in the `evidence` field.

### Run the Flutter app locally

The complete Flutter project is in `flutter_application/`. Use that directory, not `flutter_application_1/` (the latter is an incomplete generated Android project without a `pubspec.yaml`).

#### Prerequisites

- Flutter SDK installed and available as `flutter` in PowerShell.
- Python dependencies installed with `pip install -r requirements.txt`.
- A `.env` file containing valid Neo4j credentials.
- Ollama running locally with a model installed:

```powershell
ollama list
```

If no model is installed, pull one first:

```powershell
ollama pull deepseek-r1:7b
```

#### Terminal 1: start the RAG API

From the repository root, run:

```powershell
python rag.py --neo4j --serve --approach concept
```

Leave this terminal running. A successful start prints:

```text
RAG API listening on http://127.0.0.1:8000
```

If `deepseek-r1:7b` takes too long to answer, test with the smaller installed model:

```powershell
$env:OLLAMA_MODEL = "mistral:7b"
python rag.py --neo4j --serve --approach concept
```

#### Terminal 2: run Flutter

Open a second terminal and run:

```powershell
cd flutter_application
flutter pub get
flutter run
```

Choose an available device when Flutter asks. For Windows, Chrome, or another desktop target, the app connects to `http://127.0.0.1:8000/query`. For the Android emulator, the app automatically uses `http://10.0.2.2:8000/query` to reach the host computer.

#### Test the API without Flutter

You can ask a question directly from a second PowerShell terminal:

```powershell
$body = @{ query = 'What is Garo?' } | ConvertTo-Json; (Invoke-RestMethod -Uri 'http://127.0.0.1:8000/query' -Method Post -ContentType 'application/json' -Body $body).answer
```

To ask another question, replace the text inside `query`:

```powershell
$body = @{ query = 'Where do the Garo people live?' } | ConvertTo-Json; (Invoke-RestMethod -Uri 'http://127.0.0.1:8000/query' -Method Post -ContentType 'application/json' -Body $body).answer
```

Check that the API is running:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/health'
```

If PowerShell displays `>>`, press `Ctrl+C` and rerun the one-line command. This means PowerShell received an incomplete command, often because of an unmatched quote or trailing backtick. Stop the RAG API with `Ctrl+C` in Terminal 1.

Drop `--query` and it starts an interactive session where you can type multiple questions in a row:

```bash
docker compose exec app python rag.py --kg output/your_paper_kg.csv --approach concept
```

## Running the extraction validator standalone

If you want to check a JSON file of triples without running the full pipeline:

```bash
docker compose exec app python Extraction_Check.py path/to/file.json
```

Add `--strict` to enforce strict `UPPER_SNAKE_CASE` predicates instead of the relaxed default.

---

## Testing prompt changes without touching Neo4j

Two standalone scripts let you test the extraction step in isolation, on a single page of a PDF, without running the full pipeline and without touching Neo4j at all. Both import `chunk_text`, `extract_triples_from_chunk`, and `deduplicate_triples` directly from `kg_extractor.py` — the prompt, the Ollama call, the chunking, and the parser are exactly what `main.py` uses, never reimplemented. Neither script imports `neo4j_loader` or `config.py`, and neither ever calls `add_triples()`.

### `test_extraction.py` — test the current baseline prompt

Runs the pipeline's current extraction prompt (no changes) against one page and writes a CSV.

```bash
docker compose exec app python test_extraction.py papers/garo_1.pdf 3
```

- First argument: PDF path. Second argument: 1-indexed page number.
- `--model` — Ollama model name (default `deepseek-r1:7b`)
- `--out-dir` — where to write the CSV (default `output/`, which is the Docker-mounted volume — anything written elsewhere won't be visible on your host machine)

Output: `output/<pdf_name>_page<N>_test.csv` with columns `page_number, subject, predicate, object, confidence_score`.

### `test_extraction_variants.py` — A/B test a prompt variant

Same idea, but lets you swap in one of a few prompt variants instead of the baseline, so you can compare a specific instruction change without editing `kg_extractor.py`. Each variant is the baseline prompt plus exactly one added instruction, so any difference in output is attributable to that one change:

- `baseline` — the current PR007 prompt, unchanged
- `A` — adds an instruction to prefer the most specific subject entity available (e.g. `GaroMen`, `GaroWomen`, `AttireStyles`) instead of defaulting to a broad subject like `GaroCommunity`
- `B` — adds an instruction to keep predicate naming consistent for the same kind of relationship, instead of inventing a new predicate each time
- `C` — both `A` and `B` combined

```bash
docker compose exec app python test_extraction_variants.py papers/garo_1.pdf 3 --variant A
```

`--variant` is required (`baseline`, `A`, `B`, or `C`). `--model` and `--out-dir` work the same as above. Output: `output/<pdf_name>_page<N>_variant<X>.csv`, same columns as above.

`kg_extractor.py` is never modified on disk — the variant is swapped in only for the lifetime of that one process.

---

## Comparing extraction/verification configurations (strict prompt, deterministic gates)

Three configurations can now be compared on the same ground-truth pages, using the
harness in `eval/` and `prompts/` (see
`docs/superpowers/specs/2026-09-21-extraction-verification-design.md` for the full
design). None of this touches Neo4j.

1. Run each configuration against a page you have ground truth for (e.g. page 3) and
   save the output CSV:
   - **(A) Current live prompt** (unchanged): `python test_extraction.py papers/garo_1.pdf 3`
   - **(B) Strict tacit-only prompt**: `python test_extraction_prompt_config.py papers/garo_1.pdf 3 --prompt extraction_strict_tacit_v1`
   - **(C) Broad-v2 + gates**: `python test_extraction_prompt_config.py papers/garo_1.pdf 3 --prompt extraction_broad_v2`,
     then `python run_verification_pipeline.py output/<the_csv_from_broad_v2> --wellformedness-check --grounding-check --quote-check --pdf papers/garo_1.pdf`.
     `test_extraction_prompt_config.py` (unlike `test_extraction_variants.py`) always
     preserves the model's `SENTENCE REF` line into a `sentence_ref` column, which the
     grounding and quote gates both read.
2. Score each resulting CSV against the ground truth. Each CSV must already be scoped
   to the pages passed via `--pages` — `eval/run_eval.py` does not filter rows by page
   itself:
   ```bash
   python -m eval.run_eval output/<csv_from_A> --pages 3 --label "A: live prompt"
   python -m eval.run_eval output/<csv_from_B> --pages 3 --label "B: strict tacit-only"
   python -m eval.run_eval output/<csv_from_C>_refined.csv --pages 3 --label "C: broad-v2 + gates"
   ```
3. Compare the rows in `eval/results.csv` (git-tracked) for precision/recall/F1
   (strict + lenient), `gt_miss_rate`, and triples/page. Check
   `output/<...>_wellformedness_flags.csv`, `_grounding_flags.csv`, and
   `_quote_flags.csv` for anything worth a manual look.

   **`gt_miss_rate` is not a hallucination rate.** It's `1 - precision_strict`:
   the fraction of extracted triples with no *exact* string match to a row in
   the ground-truth workbook. A triple can miss here for being genuinely wrong,
   or for being real but phrased differently, using a coarser/finer subject
   than the human annotator chose, or covering something the ground-truth
   sheet simply didn't enumerate -- all observed in practice (e.g. the
   strict-tacit prompt's `GaroCommunity -WEARS-> Saree` vs. the ground truth's
   `GaroWomen -WEARS-> sarees`: same fact, coarser subject, still counted as a
   miss). For an actual grounding-based hallucination measure -- does each
   triple's own cited sentence_ref genuinely appear on its page, and does the
   triple's Subject/Object actually appear in that citation -- use
   `eval/hallucination.py`'s `compute_hallucination_rate()`, or pass `--pdf` to
   `eval/run_eval.py` to log it (as `hallucination_rate` + `citation_coverage`)
   alongside the ground-truth comparison. Always read `hallucination_rate`
   next to `citation_coverage`: a low coverage means the extraction path isn't
   populating `sentence_ref` at all (the live prompt's `test_extraction.py`
   path does this -- 0/35 on garo_1 page 3), so the rate has no evidence
   behind it, not that everything is fabricated.
4. `run_verification_pipeline.py` needs no Ollama connection at all: every gate it
   runs is deterministic and LLM-free. Only the extraction step ahead of it calls a
   model.

### No-human-review hardening (autonomous chatbot target)

> **Removed 2026-09-29 (1 of 2): the direction/ontology check** (`--direction-check`,
> `verification/direction_check.py`, `verification/predicate_directions.py`).
> Measured per-gate over the full 303-row `garo_1` dry run, it flagged **0
> rows and uniquely flagged 0**. Its curated lexicon covered 4 predicates
> (`PROHIBITS`, `REQUIRES`, `GOVERNS`, `TEACHES`) against the **110 distinct
> predicates** the corpus actually produced, and firing required the subject
> AND the object to look swapped simultaneously. The gates carrying the load
> are `--grounding-check` (99 unique catches) and `--quote-check` (45);
> `--wellformedness-check` contributed 1. Passages below dated before this
> that mention `--direction-check` are historical measurements, left as
> recorded. The code is recoverable from git history if a future corpus makes
> it earn its place.

> **Removed 2026-09-29 (2 of 2): the two-step LLM verify pass**
> (`--verify`, `--verify-samples`, `verification/verify_pass.py`,
> `prompts/verify_tacit_evidence_v1.txt`, and the `_reviewed_out.csv`
> output). It was already opt-in, showed no measured reduction in
> hallucination rate beyond the deterministic gates on this corpus, and cost
> 8+ hours of CPU-Ollama time on a single paper. Removing it is the largest
> single code reduction in the harness and changes default behaviour by
> nothing, since it was already off by default. `pruner/llm_judge.py` remains
> a live, separate implementation of the same idea if an LLM judge is wanted
> again. Passages below that describe verify bands, thresholds or sampling
> are historical, left as recorded.

This pipeline feeds a fully autonomous chatbot with no human curation step, so a
false positive here reaches an end user directly. Four things bias it toward
recall loss over hallucination risk:

- **The deterministic checks are a hard gate on `_refined.csv`**, not just an
  audit-trail side channel — a flagged row is excluded from `_refined.csv`,
  and the flag is still recorded in its own `_<check>_flags.csv` for
  inspection; it just no longer doubles as an allow-list.
- **`--grounding-check`** (off by default): a deterministic, LLM-free hard gate
  — every word of a triple's Subject and Object (see `verification/grounding_check.py`)
  must appear in its own `sentence_ref`, case-insensitively; no `sentence_ref`
  at all fails closed. Added after full-corpus validation showed the (since
  removed) LLM verify pass's plausibility judgment alone isn't reliable (see
  below) — it judged "does this relate to the sentence", not "does the
  sentence actually say this".

  **Update, 2026-10-04: the gate now also bounds the citation's length.** A
  `sentence_ref` longer than `MAX_SENTENCE_REF_CHARS` (200) is flagged as a
  paragraph rather than the single sentence the triple was read from. Reason:
  word-presence grounding gets *easier* to satisfy the longer the citation
  runs, so the gate as originally written rewarded verbose citations. On the
  2026-09-29 `garo_1.pdf` run that was a live defect, not a theoretical one —
  4 of 17 surviving triples shared one 772-char, five-sentence paragraph as
  their citation and all 4 passed grounding, while the *correctly* cited
  population triple (`POPULATION -> 76,846`, cited to "There are only 76,846
  Garo people in bangladesh") was rejected for quoting too tightly. The bound
  is a rule inside this gate, not a new gate. Measured on that run: it flags
  35 of 315 pre-gate rows (sole reason for 14 of them) and takes survivors
  17 -> 13, removing exactly the 4 paragraph-cited rows and nothing else;
  known defects among survivors go 6/17 (35%) -> 2/13 (15%). Gates still run
  in ~1.3s. Note the 200-char ceiling does also flag some genuinely
  single-sentence citations (the longest honest ones in the corpus run
  233-356 chars); none survived the other gates, and over-rejecting a precise
  citation costs recall while under-rejecting a verbose one ships a wrong
  fact, so the bound deliberately errs toward rejection.
- **`--quote-check`** (off by default, requires `--pdf`): a deterministic,
  LLM-free hard gate — the triple's `sentence_ref` must be a genuine, verbatim
  quote from its own page of `--pdf` (see `verification/quote_check.py`),
  tolerant of a `...`-truncated quote (each segment either side of the
  ellipsis must independently be genuine). Catches a failure mode
  `--grounding-check` structurally can't: a triple whose Subject/Object words
  are all present in *some* sentence, but where that sentence itself was
  invented or blended from two different real sentences (a fabricated or
  imprecise citation wrapped around an otherwise-plausible claim). Found
  during a manual audit of the strict-tacit-only prompt's output — a triple
  can look "grounded" against its own citation while the citation itself
  isn't real.
- **`--wellformedness-check` also flags tautological Subject/Object pairs**
  (see `verification/wellformedness_check.py`'s `_check_tautology`) — e.g.
  "Types of baskets" `HAS_TYPE` "Different types of baskets" restates the same
  concept rather than expressing a real relationship. Subject/Object word sets
  are compared after stripping qualifier words ("different", "various", "the",
  "of", etc.); an exact match after stripping is flagged.

There is deliberately no "held for human review" path in this pipeline — a
triple flagged by any enabled check is dropped, not queued. Every dropped row
is still recorded in the flag file of whichever gate caught it, but nothing
downstream reads those automatically.

**Full-corpus validation (2026-09-24):** running the hardened pipeline on
page 3 alone scored a 0% `gt_miss_rate` (2 kept, both correct) — but that was a
2-sample artifact. Across all 7 ground-truth pages (148 GT triples), it
scored 18 kept / **89% `gt_miss_rate`** (strict precision 0.11). Adding
`--grounding-check` on top brought that down to 3 kept / **33%
`gt_miss_rate`** (strict precision 0.67) — a large improvement, but not zero.
The one remaining false positive in that run was a malformed, tautological
entity pair ("Types of baskets" `HAS_TYPE` "Different types of baskets").
Adding the tautology check to `check_wellformedness` (above) catches exactly
that case: full-corpus result with direction + wellformedness + grounding
all enabled is 2 kept / **0% `gt_miss_rate`** (strict precision 1.00, recall
0.01 — 2/148 GT triples). Given the product goal (a fully autonomous chatbot
with zero tolerance for returning false information, and no human review
step), this low-recall/zero-`gt_miss_rate` trade is the intended and accepted
outcome, not a shortfall to fix. Always validate any threshold/gate change
against the full ground-truth corpus (all 7 pages), not a single page — see
`eval/results.csv` for the `"C-hardened..."`-labeled rows.

**These are `gt_miss_rate` numbers, not hallucination rates** (see the caveat
above) — re-scoring the same files with `eval/hallucination.py`'s real,
grounding-based check (independent of the ground-truth workbook, so it also
works on papers with no ground truth at all) tells a related but distinct
story: raw candidates were 91% flagged, the direction+wellformedness-only
stage (18 kept) was still 83% flagged, but the moment `--grounding-check`
enters the gate the flagged rate drops straight to **0%** (3 kept, and stays
0% at 2 kept after adding the tautology check) — the *same* deterministic
grounding gate that was tuned against `gt_miss_rate` independently zeroes out
the real, text-grounded hallucination rate too. Re-running this whole
pipeline on a second, unrelated paper (`garo_2.pdf`, 22 pages, no ground
truth) replicates it: 268 raw candidates, 91.8% flagged; 18 gate-survivors,
22.2% flagged; 2 final kept (after the LLM verify pass), one flagged for a
trivial one-word paraphrase in its own quote ("This study..." extracted as
"The study..."), not a fabrication.

---

## Known Issues

- **Low/zero triple counts after validation:** DeepSeek R1 7B doesn't always follow the requested `(Subject)-[PREDICATE]->(Object)` output format — sometimes it writes plain prose instead. When this happens, the parser can't extract a real triple and falls back to a placeholder, which the validation gate now correctly rejects. This shows up as most or all chunks getting rejected in Step 6. **This is a known, pre-existing bug, not something a fresh checkout or your setup is doing wrong.** If you hit this consistently, flag it in the group chat rather than trying to fix it solo — it's being tracked.
- **`rag.py --approach cypher` returns no results:** known limitation, use `--approach concept` instead (see above). This isn't a priority fix right now.

## Troubleshooting

- **`unable to get image... check if the daemon is running`**: Docker Desktop isn't open. Open it from your Start menu / Applications and wait for the whale icon to settle, then retry.
- **`Conflict. The container name "/mandi_kg_ollama" is already in use`**: you (or a past run) already have a container with this name, possibly from a different project folder. Run `docker ps -a` to see what's there, then `docker rm -f mandi_kg_ollama` and `docker rm -f mandi_kg_app` before retrying `docker compose up --build -d`.
- **`can't open file '/app/Extraction_Check.py': No such file or directory`** (or any script): the file exists on your machine but the container hasn't been rebuilt since it was added. Run `docker compose up --build -d` again — Docker only copies files in at build time.
- **"Connection refused" to Ollama**: make sure the containers are still running (`docker compose ps`) — the `app` container must reach `ollama` over the internal Docker network (`http://ollama:11434`), not `localhost`.
- **Neo4j connection errors**: double-check your `.env` values, and confirm the AuraDB instance hasn't auto-paused from inactivity (check the Aura console, or ask Aidan).
- **Slow extraction**: DeepSeek R1 7B runs on CPU by default inside the container, so each chunk can take a while — this is normal, especially without GPU passthrough set up.
- **Model re-downloading every time**: means the `ollama_models` volume isn't persisting. Check you didn't run `docker compose down -v` (the `-v` flag deletes volumes along with containers).

---

## Running without Docker (alternative)

If you'd rather set things up natively:

### 1. Install Ollama

Windows: download from https://ollama.com
macOS/Linux: `curl -fsSL https://ollama.com/install.sh | sh`

### 2. Start Ollama and pull the model

```bash
ollama serve
ollama pull deepseek-r1:7b
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up `.env` (same as Docker Step 3 above)

### 5. Run

```bash
python main.py papers/your_paper.pdf              # gated, then uploads
python main.py papers/your_paper.pdf --dry-run    # gated, uploads nothing
python main.py papers/your_paper.pdf --no-gates   # pre-2026-10-04 behaviour
```

Running outside Docker also needs the spaCy model the subject-specificity step
depends on, which the Dockerfile installs for you:

```bash
python -m spacy download en_core_web_sm
```

---

## Viewing the Knowledge Graph

Go to https://browser.neo4j.io/ and enter your connection details from `.env`:
- URI: `NEO4J_URI`
- User: `NEO4J_USERNAME`
- Password: `NEO4J_PASSWORD`

```cypher
MATCH (n)-[r]->(m)
RETURN n, r, m
LIMIT 100
```

Count relationships:

```cypher
MATCH ()-[r]->()
RETURN count(r)
```