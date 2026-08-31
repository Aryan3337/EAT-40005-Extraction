import sys
from pathlib import Path

from kg_extractor import run_kg_extraction, save_triples_to_csv
from neo4j_loader.insert import add_triples
from Extraction_Check import validate_triple_format, flag_artifact_triples

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

    # ------------------------------------------------------------
    # Validation gate: structural checks + artifact filtering,
    # run before anything reaches Neo4j.
    # ------------------------------------------------------------
    print("\nRunning validation gate...")
    valid_triples = []
    rejected_count = 0

    for triple in triples:
        try:
            validate_triple_format(triple)
            valid_triples.append(triple)
        except AssertionError as e:
            rejected_count += 1
            print(f"  [REJECTED] {triple.get('subject', '?')}: {e}")

    print(f"Validation: {len(valid_triples)} passed, {rejected_count} rejected.")

    # Artifact filtering: exclude research-methodology triples entirely
    # rather than just warning, since they aren't real community knowledge.
    flagged = flag_artifact_triples(valid_triples)
    if flagged:
        flagged_indices = {item['index'] for item in flagged}
        print(f"\n[FILTERED] Excluding {len(flagged)} triples that matched research-methodology artifacts:")
        for item in flagged:
            t = item['triple']
            print(f"  - ({t['subject']})-[{t['predicate']}]->({t['object']})  [matched: '{item['matched_keyword']}']")
        valid_triples = [t for i, t in enumerate(valid_triples) if i not in flagged_indices]
        print(f"Remaining after artifact filtering: {len(valid_triples)}")

    if not valid_triples:
        print("\nNo valid triples remained after validation and filtering. Skipping save and upload.")
        sys.exit(0)

    # Local backup CSV, written before the Neo4j upload so results are on
    # disk even if the upload fails partway through.
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    paper_name = Path(pdf_path).stem
    csv_path = output_dir / f"{paper_name}_kg.csv"
    save_triples_to_csv(valid_triples, str(csv_path), paper_name)
    print(f"Saved local backup to {csv_path}")

    add_triples(valid_triples)
else:
    print("No triples extracted.")