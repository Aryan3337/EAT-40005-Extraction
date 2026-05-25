#!/usr/bin/env python3
"""
Knowledge Graph Extraction from Academic Papers using Ollama
Outputs CSV with columns: extraction_number, paper, subject, predicate, object, source_section, confidence, passage, sentence_ref
"""

import sys
import json
import csv
import re
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any
import requests
import pdfplumber

# ============================================================
# 1. Text Extraction from PDF
# ============================================================
def extract_text_from_pdf(pdf_path: str) -> str:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text()
            if page_text:
                text += f"\n===== Page {page_num} =====\n"
                text += page_text + "\n"
    return text

# ============================================================
# 2. Chunking
# ============================================================
def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> List[Tuple[str, int]]:
    page_pattern = r"(===== Page \d+ =====\n)"
    parts = re.split(page_pattern, text)
    pages = []
    for i in range(1, len(parts), 2):
        if i+1 < len(parts):
            header = parts[i]
            content = parts[i+1]
            page_match = re.search(r"===== Page (\d+) =====", header)
            page_num = int(page_match.group(1)) if page_match else 0
            pages.append((page_num, content))
    chunks_with_page = []
    for page_num, page_content in pages:
        if not page_content.strip():
            continue
        start = 0
        length = len(page_content)
        while start < length:
            end = min(start + chunk_size, length)
            chunk = page_content[start:end]
            chunks_with_page.append((chunk.strip(), page_num))
            start += chunk_size - overlap
    return chunks_with_page

# ============================================================
# 3. Ollama API call with custom prompt
# ============================================================
OLLAMA_URL = "http://localhost:11434/api/generate"

def make_extraction_prompt(chunk_text: str) -> str:
    return f"""You are a knowledge graph extraction assistant. You will be provided with a passage from an academic research paper.

Read the passage. Identify every factual claim, relationship, practice, observation, or piece of knowledge about the Garo / Mandi community discussed in the passage.

For each meaningful piece, output a Cypher comment block in this exact format:

// PASSAGE: <paraphrased passage — retain all factual content, remove filler words, following this format (GaroWomen)-[ARE_KNOWN_AS]->(SkilledBeauticians)>
// SENTENCE REF: <exact sentence from the paper this was drawn from>
// SOURCE: <paper title placeholder>

Rules:
- Do not decide in advance what topics or domains to look for — extract everything factual the passage contains.
- Each passage must be traceable to a specific sentence.
- Output only the formatted comment blocks. No explanation or prose.

Passage:
{chunk_text}
"""

def parse_ollama_blocks(raw_response: str, page_num: int) -> List[Dict[str, str]]:
    blocks = re.split(r'\n\s*// PASSAGE:', raw_response, flags=re.IGNORECASE)
    triples = []
    for block in blocks:
        if not block.strip():
            continue
        passage_match = re.search(r'^(.*?)(?=\n// SENTENCE REF:|$)', block, re.DOTALL)
        passage_text = passage_match.group(1).strip() if passage_match else ""
        sent_match = re.search(r'// SENTENCE REF:\s*(.*?)(?=\n// SOURCE:|$)', block, re.DOTALL)
        sentence_ref = sent_match.group(1).strip() if sent_match else ""
        src_match = re.search(r'// SOURCE:\s*(.*?)$', block, re.DOTALL)
        source = src_match.group(1).strip() if src_match else "Unknown"
        triple_match = re.search(r'\(([^)]+)\)\s*-\s*\[([^\]]+)\]\s*->\s*\(([^)]+)\)', passage_text)
        if triple_match:
            subject = triple_match.group(1).strip()
            predicate = triple_match.group(2).strip()
            obj = triple_match.group(3).strip()
            triples.append({
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "source_section": f"Page {page_num}",
                "confidence": "High",
                "passage": passage_text,
                "sentence_ref": sentence_ref,
                "source": source
            })
        else:
            triples.append({
                "subject": "UNKNOWN",
                "predicate": "UNKNOWN",
                "object": "UNKNOWN",
                "source_section": f"Page {page_num}",
                "confidence": "Low",
                "passage": passage_text,
                "sentence_ref": sentence_ref,
                "source": source
            })
    return triples

def extract_triples_from_chunk(chunk_text: str, page_num: int, model: str, retries: int = 2) -> List[Dict[str, str]]:
    prompt = make_extraction_prompt(chunk_text)
    for attempt in range(retries):
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 2048}
                },
                timeout=120
            )
            if response.status_code != 200:
                return []
            result = response.json()
            raw_text = result.get("response", "")
            triples = parse_ollama_blocks(raw_text, page_num)
            if triples:
                return triples
        except Exception:
            time.sleep(1)
    return []

# ============================================================
# 4. Deduplication
# ============================================================
def deduplicate_triples(triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {}
    for t in triples:
        if not isinstance(t, dict):
            continue
        if not all(k in t for k in ["subject", "predicate", "object"]):
            continue
        key = f"{t['subject'].lower().strip()}|{t['predicate'].lower().strip()}|{t['object'].lower().strip()}"
        if key not in seen:
            seen[key] = t
        else:
            if t.get('confidence') == 'High' and seen[key].get('confidence') != 'High':
                seen[key] = t
    return list(seen.values())

# ============================================================
# 5. Save to CSV with sequential numbering
# ============================================================
def save_triples_to_csv(triples: List[Dict], output_path: str, paper_name: str):
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['extraction_number', 'paper', 'subject', 'predicate', 'object', 'source_section', 'confidence', 'passage', 'sentence_ref']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, t in enumerate(triples, start=1):
            writer.writerow({
                'extraction_number': idx,
                'paper': paper_name,
                'subject': t.get('subject', ''),
                'predicate': t.get('predicate', ''),
                'object': t.get('object', ''),
                'source_section': t.get('source_section', 'Unknown'),
                'confidence': t.get('confidence', 'Medium'),
                'passage': t.get('passage', ''),
                'sentence_ref': t.get('sentence_ref', '')
            })

# ============================================================
# 6. Main Pipeline
# ============================================================
def run_kg_extraction(pdf_path: str, model: str = "mistral:7b"):
    print(f"1. Extracting text from {pdf_path}...")
    full_text = extract_text_from_pdf(pdf_path)
    if not full_text.strip():
        print("No text extracted.")
        return

    print("2. Chunking text...")
    chunks = chunk_text(full_text, chunk_size=1500, overlap=200)
    print(f"   Created {len(chunks)} chunks.")

    print("3. Extracting triples with Ollama...")
    all_triples = []
    for idx, (chunk, page_num) in enumerate(chunks):
        print(f"   Chunk {idx+1}/{len(chunks)} (page ~{page_num})...", end=" ", flush=True)
        triples = extract_triples_from_chunk(chunk, page_num, model)
        all_triples.extend(triples)
        print(f"got {len(triples)} triples")
        time.sleep(0.3)

    print(f"   Total raw triples: {len(all_triples)}")

    print("4. Deduplicating...")
    unique = deduplicate_triples(all_triples)
    print(f"   Kept {len(unique)} unique triples.")

    high = sum(1 for t in unique if t.get('confidence') == 'High')
    print(f"   High confidence: {high}")

    output_csv = Path(pdf_path).stem + "_kg_extractions.csv"
    paper_name = Path(pdf_path).stem
    save_triples_to_csv(unique, output_csv, paper_name)
    print(f"5. Saved to {output_csv}")
    print("Done!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <path_to_pdf> [model_name]")
        print("Example: python script.py paper.pdf mistral:7b")
        sys.exit(1)

    pdf_file = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else "mistral:7b"

    if not Path(pdf_file).exists():
        print(f"File not found: {pdf_file}")
        sys.exit(1)

    run_kg_extraction(pdf_file, model)