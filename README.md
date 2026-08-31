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
Validation Gate (structure check + research-artifact flagging)
        ↓
Neo4j Upload
        ↓
Knowledge Graph
```

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
5. Any **`[WARN]`** lines flagging triples that look like research-methodology artifacts (interview/participant language) rather than real cultural content — these aren't blocked, just flagged for manual review
6. A local CSV backup saved to `output/<paper_name>_kg.csv`
7. Upload confirmation: `Uploaded N triples to Neo4j.`

**If you see `Validation: 0 passed` or very few triples survive:** this is a known issue, not something you broke. See **Known Issues** below.

### Step 7: Stopping the containers

```bash
docker compose down
```

Your downloaded model and `.env` config are preserved — starting again won't require re-downloading anything.

---

## Running the RAG query tool

Once you've got triples in a CSV (from Step 6), you can query them directly without going through Neo4j:

```bash
docker compose exec app python rag.py --kg output/your_paper_kg.csv --query "Where do the Garo people live?" --approach concept
```

Use `--approach concept` (recommended, fast, no LLM needed) rather than `--approach cypher` — the Cypher approach currently has a known issue (see below) and returns empty results.

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
python main.py papers/your_paper.pdf
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