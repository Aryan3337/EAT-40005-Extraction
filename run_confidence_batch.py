import subprocess
import sys
from pathlib import Path

base_dir = Path(__file__).resolve().parent

papers_dir = base_dir / "approved_papers"
framework = base_dir / "confidence_framework_update.py"
extractor = base_dir / "kg_extractor.py"
output_dir = base_dir / "extraction_outputs"

output_dir.mkdir(exist_ok=True)

if not framework.exists():
    print(f"ERROR: Confidence framework not found: {framework}")
    sys.exit(1)

if not extractor.exists():
    print(f"ERROR: KG extractor not found: {extractor}")
    sys.exit(1)

pdfs = sorted(papers_dir.glob("*.pdf"))

print(f"Found {len(pdfs)} papers.\n")

results = []

for i, pdf in enumerate(pdfs, start=1):
    print("\n" + "=" * 80)
    print(f"[{i}/{len(pdfs)}] PAPER: {pdf.name}")
    print("=" * 80)

    print("\nSTEP 1: Confidence check")

    confidence_result = subprocess.run(
        [
            sys.executable,
            str(framework),
            str(pdf),
            "--model",
            "mistral:7b"
        ],
        text=True
    )

    if confidence_result.returncode == 0:
        status = "APPROVED"

    elif confidence_result.returncode == 2:
        status = "MANUAL REVIEW"

    elif confidence_result.returncode == 1:
        status = "REJECTED"

    else:
        status = f"ERROR ({confidence_result.returncode})"

    print(f"\nConfidence outcome: {status}")

    extraction_status = "NOT RUN"

    if status == "APPROVED":
        expected_output = (
            output_dir /
            f"{pdf.stem}_extractions.csv"
        )

        if expected_output.exists():
            print(
                f"Extraction already exists, skipping: "
                f"{expected_output.name}"
            )
            extraction_status = "ALREADY EXISTS"

        else:
            print("\nSTEP 2: KG extraction")

            extraction_result = subprocess.run(
                [
                    sys.executable,
                    str(extractor),
                    str(pdf),
                    "mistral:7b"
                ],
                text=True
            )

            if extraction_result.returncode == 0:
                extraction_status = "EXTRACTED"
            else:
                extraction_status = (
                    f"EXTRACTION ERROR "
                    f"({extraction_result.returncode})"
                )

    elif status == "MANUAL REVIEW":
        print(
            "Skipping extraction until manual review is resolved."
        )
        extraction_status = "MANUAL REVIEW"

    elif status == "REJECTED":
        print("Skipping extraction because paper was rejected.")
        extraction_status = "SKIPPED"

    else:
        print("Skipping extraction because confidence check errored.")
        extraction_status = "ERROR"

    results.append(
        (
            pdf.name,
            status,
            extraction_status
        )
    )


print("\n\nFINAL SUMMARY")
print("=" * 100)

for name, confidence_status, extraction_status in results:
    print(
        f"{confidence_status:15} | "
        f"{extraction_status:20} | "
        f"{name}"
    )
