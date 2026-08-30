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
Neo4j Upload
        ↓
Knowledge Graph
```

## Running with Docker (recommended)

You don't need Python, Ollama, or any dependencies installed locally — Docker handles all of it. This is the easiest way to get the pipeline running if you've never set any of this up before.

### 1. Install Docker Desktop

Download and install from https://www.docker.com/products/docker-desktop — this works on Windows, macOS, and Linux. Open Docker Desktop once after installing to make sure it's running (you'll see a whale icon in your system tray/menu bar).

### 2. Clone the repo and set up your `.env` file

```bash
git clone <repo-url>
cd EAT-40005-Extraction
```

Copy the example environment file:

```bash
cp .env.example .env
```

(On Windows PowerShell: `copy .env.example .env`)

Open `.env` and fill in the real Neo4j credentials — ask a team member (Aidan has the AuraDB instance) for these. **Never commit `.env`** — it's already excluded via `.gitignore`.

NEO4J_URI=neo4j+s://your-instance-id.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password-here


### 3. Build and start the containers

```bash
docker compose up --build
```

This starts two containers:
- **`ollama`** — runs the local LLM server (DeepSeek R1 7B)
- **`app`** — the Python environment with the extraction pipeline, connected to `ollama` internally

First run will take a while as it builds the Python image and starts Ollama. Leave this running in its own terminal, or add `-d` to run it in the background (`docker compose up --build -d`).

### 4. Pull the DeepSeek model (first time only)

In a **new terminal window**, run:

```bash
docker compose exec ollama ollama pull deepseek-r1:7b
```

This downloads the model (~4.7GB) into a Docker volume, so you only need to do this once — it survives container rebuilds.

### 5. Add a paper and run extraction

Drop a PDF into the `papers/` folder in the project root, then run:

```bash
docker compose exec app python main.py papers/your_paper.pdf
```

Output triples are saved to `output/<paper_name>_kg.csv` and also uploaded directly to Neo4j.

### 6. Stopping the containers

```bash
docker compose down
```

Your downloaded model and `.env` config are preserved — running `docker compose up` again won't require re-downloading the model.

## Troubleshooting

- **"Connection refused" to Ollama**: make sure `docker compose up` is still running in its terminal — the `app` container talks to `ollama` over the internal Docker network (`http://ollama:11434`), not `localhost`.
- **Neo4j connection errors**: double check your `.env` values are correct and that the AuraDB instance hasn't auto-paused from inactivity (check the Aura console — Aidan can help resolve this).
- **Slow extraction**: DeepSeek R1 7B runs on CPU inside the container by default, so expect each chunk to take a while, especially on laptops without a dedicated GPU passthrough set up.
- **Model re-downloading every time**: this means the `ollama_models` volume isn't persisting — check you didn't run `docker compose down -v` (the `-v` flag deletes volumes).

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

### 4. Set up `.env` (same as Docker step 2 above)

### 5. Run

```bash
python main.py papers/your_paper.pdf
```

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