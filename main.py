import sys
from pathlib import Path

from kg_extractor import run_kg_extraction
from neo4j_loader.insert import add_triples

if len(sys.argv) < 2:
    print("Usage: python main.py <path_to_pdf> [model_name]")
    sys.exit(1)

pdf_path = sys.argv[1]
model = sys.argv[2] if len(sys.argv) > 2 else "mistral:7b"

if not Path(pdf_path).exists():
    print(f"File not found: {pdf_path}")
    sys.exit(1)

triples = run_kg_extraction(pdf_path, model)

print(f"Extracted {len(triples)} triples.")

if triples:
    # Preserve the original PDF filename for source traceability
    source_file = Path(pdf_path).name

    for triple in triples:
        triple["source_file"] = source_file

    add_triples(triples)
else:
    print("No triples extracted.")
