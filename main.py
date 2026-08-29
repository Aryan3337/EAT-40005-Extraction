import sys
from pathlib import Path

from kg_extractor import run_kg_extraction, save_triples_to_csv
from neo4j_loader.insert import add_triples

if len(sys.argv) < 2:
    print("Usage: python main.py <path_to_pdf> [model_name]")
    sys.exit(1)

pdf_path = sys.argv[1]
model = sys.argv[2] if len(sys.argv) > 2 else "deepseek-r1:7b"

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

    # Local backup CSV, written before the Neo4j upload so results are on
    # disk even if the upload fails partway through.
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    paper_name = Path(pdf_path).stem
    csv_path = output_dir / f"{paper_name}_kg.csv"
    save_triples_to_csv(triples, str(csv_path), paper_name)
    print(f"Saved local backup to {csv_path}")

    add_triples(triples)
else:
    print("No triples extracted.")
