# Knowledge Graph Extraction Backend

Automatically extract knowledge graph triples from academic PDF papers using a local LLM (Ollama + Mistral) and upload them directly into a Neo4j database.

## Overview

This backend provides an end-to-end pipeline that converts unstructured academic papers into a structured knowledge graph.

### Pipeline

```text
PDF Research Paper
        ↓
Text Extraction
        ↓
Text Chunking
        ↓
LLM Triple Extraction (Ollama + Mistral)
        ↓
Deduplication
        ↓
Neo4j Upload
        ↓
Knowledge Graph
```

## Requirements

- Windows / macOS / Linux
- Python 3.10+
- Ollama installed (https://ollama.com)
- Neo4j Aura account and database instance
- At least 8GB RAM (16GB recommended)

## Installation

### 1. Install Ollama

Windows: Download from https://ollama.com

macOS/Linux:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Start the Ollama Server

```bash
ollama serve
```

### 3. Download the Mistral Model

```bash
ollama pull mistral:7b
```

### 4. Install Python Dependencies

```bash
pip install -r requirements.txt
```

Or:

```bash
pip install neo4j python-dotenv pdfplumber requests
```

## Usage

```bash
python main.py your_paper.pdf mistral:7b
```

Example:

```bash
python main.py paper.pdf mistral:7b
```

## What Happens During Execution

1. Extract text from the PDF.
2. Split the text into chunks.
3. Send chunks to Mistral via Ollama.
4. Extract knowledge graph triples.
5. Deduplicate triples.
6. Upload nodes and relationships to Neo4j.

## Viewing the Knowledge Graph

Go to: https://browser.neo4j.io/
 
Enter
URI: neo4j+s://cf02815e.databases.neo4j.io
user: cf02815e
password: L9t6VQGnCr55FHipQQbVGP43vM_YPdR6HElfFlxVw-w

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

