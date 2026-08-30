#!/usr/bin/env python3
"""
Knowledge Graph Extraction – DeepSeek (standalone extraction)
With auto‑approval detection and interactive user choices.
"""

import sys
import json
import csv
import re
import time
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Any
from datetime import datetime
import requests
import pdfplumber

# ============================================================
# 1. Text Extraction
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
def chunk_text(text: str, chunk_size: int = 2500, overlap: int = 400) -> List[Tuple[str, int]]:
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
# 3. Strip DeepSeek reasoning
# ============================================================
def strip_deepseek_reasoning(raw: str) -> str:
    for marker in ['(', '[', '{']:
        idx = raw.find(marker)
        if idx != -1:
            raw = raw[idx:]
            break
    raw = re.sub(r'^```(?:cypher|json)?\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw)
    return raw.strip()

# ============================================================
# 4. User-specified prompt
# ============================================================
def make_prompt(chunk: str) -> str:
    return f"""Read the paper and extract knowledge graph triples in these steps:
1. Identify informative sentences
2. Identify the main subject of each sentence
3. Extract as Subject–Predicate–Object. They should have a format like: (GaroWomen)-[ARE_KNOWN_AS]->(SkilledBeauticians)
4. Each triple needs to be referenced to a sentence, so extract the location of the sentence alongside the triple

Output each triple and its reference on one line in this exact format:
(Subject)-[PREDICATE]->(Object) | Location: "sentence text" (Page X)

Rules:
- Predicates: UPPER_CASE_WITH_UNDERSCORES
- Only extract explicit facts. No inference.
- If no triples, output nothing.

Passage:
{chunk}
"""

# ============================================================
# 5. Parse triples with reference
# ============================================================
def parse_triples_with_reference(output: str, page_num: int) -> List[Dict[str, Any]]:
    triples = []
    lines = output.split('\n')
    for line in lines:
        line = line.strip()
        triple_match = re.search(r'\(([^)]+)\)\s*-\s*\[:?([^\]]+)\]\s*->\s*\(([^)]+)\)', line)
        if triple_match:
            subject = triple_match.group(1).strip()
            predicate = triple_match.group(2).strip().upper()
            obj = triple_match.group(3).strip()
            ref_match = re.search(r'\|\s*Location:\s*["]?(.*?)["]?(?:\s*\(Page\s*(\d+)\))?$', line, re.IGNORECASE)
            if ref_match:
                sentence_ref = ref_match.group(1).strip()
                ref_page = ref_match.group(2) if ref_match.group(2) else str(page_num)
            else:
                parts = line.split('|', 1)
                sentence_ref = parts[1].strip() if len(parts) > 1 else "NO_REFERENCE"
                ref_page = str(page_num)
            triples.append({
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "source_section": f"Page {ref_page}",
                "confidence": "High",
                "passage": f"({subject})-[:{predicate}]->({obj})",
                "sentence_ref": sentence_ref
            })
    return triples

# ============================================================
# 6. Ollama extraction call
# ============================================================
OLLAMA_URL = "http://localhost:11434/api/generate"

def extract_chunk(chunk_text: str, page_num: int, model: str, retries: int = 2) -> Tuple[List[Dict], float]:
    prompt = make_prompt(chunk_text)
    start_time = time.time()
    for attempt in range(retries):
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 2048}
                },
                timeout=150
            )
            elapsed = time.time() - start_time
            if resp.status_code != 200:
                continue
            raw = resp.json().get("response", "")
            cleaned = strip_deepseek_reasoning(raw)
            triples = parse_triples_with_reference(cleaned, page_num)
            if triples:
                return triples, elapsed
        except Exception as e:
            print(f"Attempt {attempt+1} error: {e}")
            time.sleep(1)
    return [], time.time() - start_time

# ============================================================
# 7. Deduplication
# ============================================================
def deduplicate(triples: List[Dict]) -> List[Dict]:
    seen = {}
    for t in triples:
        key = f"{t['subject'].lower()}|{t['predicate']}|{t['object'].lower()}"
        if key not in seen:
            seen[key] = t
        else:
            if len(t.get('sentence_ref', '')) > len(seen[key].get('sentence_ref', '')):
                seen[key] = t
    return list(seen.values())

# ============================================================
# 8. Save CSV and JSON
# ============================================================
def save_csv(triples: List[Dict], path: str, paper: str):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['extraction_number', 'paper', 'subject', 'predicate', 'object',
                      'source_section', 'confidence', 'passage', 'sentence_ref']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, t in enumerate(triples, 1):
            writer.writerow({
                'extraction_number': idx,
                'paper': paper,
                'subject': t.get('subject', ''),
                'predicate': t.get('predicate', ''),
                'object': t.get('object', ''),
                'source_section': t.get('source_section', 'Unknown'),
                'confidence': t.get('confidence', 'Medium'),
                'passage': t.get('passage', ''),
                'sentence_ref': t.get('sentence_ref', '')
            })

def save_json(triples: List[Dict], path: str, paper: str):
    data = []
    for idx, t in enumerate(triples, 1):
        data.append({
            'extraction_number': idx,
            'paper': paper,
            'subject': t['subject'],
            'predicate': t['predicate'],
            'object': t['object'],
            'source_section': t['source_section'],
            'confidence': t['confidence'],
            'passage': t['passage'],
            'sentence_ref': t['sentence_ref']
        })
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ============================================================
# 9. Format time
# ============================================================
def format_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f} sec"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.2f}s"

# ============================================================
# 10. Helper to get command line arguments
# ============================================================
def _get_arg(name: str, default=None):
    if name in sys.argv:
        idx = sys.argv.index(name)
        if idx + 1 < len(sys.argv):
            return sys.argv[idx+1]
    return default

# ============================================================
# 11. Check if paper has been approved (looks in approved folder)
# ============================================================
def is_paper_approved(pdf_path: str) -> bool:
    approved_dir = Path("confidence_logs/approved")
    if not approved_dir.exists():
        return False
    paper_stem = Path(pdf_path).stem
    pattern = f"*_approval_{paper_stem}.json"
    matches = list(approved_dir.glob(pattern))
    return len(matches) > 0

# ============================================================
# 12. Run confidence check (external script)
# ============================================================
def run_confidence_check_external(pdf_path: str, metadata: Dict[str, Any]) -> int:
    cmd = [
        sys.executable, "confidence_framework.py",
        pdf_path,
        "--title", metadata.get("title", ""),
        "--authors", metadata.get("authors", ""),
        "--year", metadata.get("year", ""),
        "--journal", metadata.get("journal", ""),
        "--doi", metadata.get("doi", "")
    ]
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode

# ============================================================
# 13. Extraction routine (factored out)
# ============================================================
def run_extraction(pdf_path: str, model: str):
    total_start = time.time()
    print("=" * 70)
    print(f"Knowledge Graph Extraction – DeepSeek")
    print(f"PDF: {pdf_path}")
    print(f"Model: {model}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    full_text = extract_text_from_pdf(pdf_path)
    if not full_text.strip():
        print("No text extracted.")
        return
    print(f"   Done in {format_time(time.time() - step_start)}")

    chunks = chunk_text(full_text, chunk_size=2500, overlap=400)
    print(f"\nCreated {len(chunks)} chunks")

    all_triples = []
    for idx, (chunk, page) in enumerate(chunks, 1):
        print(f"Chunk {idx}/{len(chunks)} (page ~{page})...", end=" ", flush=True)
        triples, _ = extract_chunk(chunk, page, model)
        all_triples.extend(triples)
        print(f"got {len(triples)} triples")
        time.sleep(0.2)

    unique = deduplicate(all_triples)
    base_name = Path(pdf_path).stem
    save_csv(unique, f"{base_name}_kg.csv", base_name)
    save_json(unique, f"{base_name}_kg.json", base_name)

    total_time = time.time() - total_start
    print(f"\nCOMPLETED! {len(unique)} unique triples in {format_time(total_time)}")

# ============================================================
# 14. Main
# ============================================================
def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <pdf_path> [model_name] [--title ...]")
        print("Example: python script.py paper.pdf deepseek-r1:7b --title 'Paper Title' --year 2023")
        sys.exit(1)

    pdf_path = sys.argv[1]
    model = "deepseek-r1:7b"
    if len(sys.argv) > 2 and not sys.argv[2].startswith('--'):
        model = sys.argv[2]

    metadata = {
        "title":   _get_arg('--title', default=""),
        "authors": _get_arg('--authors', default=""),
        "year":    _get_arg('--year', default=""),
        "journal": _get_arg('--journal', default=""),
        "doi":     _get_arg('--doi', default="")
    }

    # Auto‑approval check
    if is_paper_approved(pdf_path):
        print("\n✅ Paper previously APPROVED by confidence framework. Running extraction automatically.")
        run_extraction(pdf_path, model)
        return

    # Not approved – show menu
    print("\n" + "="*70)
    print("Paper has NOT been approved (or no prior confidence evaluation found).")
    print("Options:")
    print("  1) Run confidence check now (recommended)")
    print("  2) Extract anyway (bypass confidence)")
    print("  3) Exit")
    choice = input("Enter choice (1/2/3): ").strip()

    if choice == '1':
        exit_code = run_confidence_check_external(pdf_path, metadata)
        if exit_code == 1:
            print("\n❌ PAPER REJECTED – extraction skipped.")
            sys.exit(1)
        elif exit_code == 2:
            print("\n⚠️ PAPER NEEDS MANUAL REVIEW")
            answer = input("Override and approve anyway? (y/N): ").strip().lower()
            if answer != 'y':
                print("Extraction skipped.")
                sys.exit(2)
            print("Manual override accepted – proceeding with extraction.")
        print("\n✅ PAPER APPROVED – starting KG extraction")
        run_extraction(pdf_path, model)

    elif choice == '2':
        print("\n⚠️ Bypassing confidence check – extraction may produce low‑quality results.")
        run_extraction(pdf_path, model)

    else:
        print("Exiting.")
        sys.exit(0)

if __name__ == "__main__":
    main()
