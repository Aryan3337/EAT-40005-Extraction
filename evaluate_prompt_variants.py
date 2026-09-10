import re
from pathlib import Path

BASE = Path("output/prompt_tests")

FILES = {
    "Baseline": BASE / "tangail_s1_s5_baseline.txt",
    "Variant A": BASE / "tangail_s1_s5_variantA.txt",
    "Variant B": BASE / "tangail_s1_s5_variantB.txt",
    "Variant C": BASE / "tangail_s1_s5_variantC.txt",
}

GROUND_TRUTH = BASE / "tangail_s1_s5_ground_truth.txt"

TRIPLE_PATTERN = re.compile(
    r"\(([^)]+)\)-\[([^\]]+)\]->\(([^)]+)\)"
)

def extract_triples(path):
    text = path.read_text(encoding="utf-8")

    triples = set()

    for subject, predicate, obj in TRIPLE_PATTERN.findall(text):
        triples.add((
            subject.strip(),
            predicate.strip(),
            obj.strip()
        ))

    return triples

ground_truth = extract_triples(GROUND_TRUTH)

print("=" * 70)
print("TANGAIL S1-S5 PROMPT EVALUATION")
print("=" * 70)
print("Ground-truth triples:", len(ground_truth))
print()

for name, path in FILES.items():

    predicted = extract_triples(path)

    correct = predicted & ground_truth
    missing = ground_truth - predicted
    extra = predicted - ground_truth

    precision = (
        len(correct) / len(predicted)
        if predicted else 0
    )

    recall = (
        len(correct) / len(ground_truth)
        if ground_truth else 0
    )

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0
    )

    print("=" * 70)
    print(name)
    print("=" * 70)

    print("Predicted:", len(predicted))
    print("Exact matches:", len(correct))
    print("Missing:", len(missing))
    print("Extra:", len(extra))

    print(f"Precision: {precision:.3f}")
    print(f"Recall:    {recall:.3f}")
    print(f"F1:        {f1:.3f}")

    print("\nExact matches:")
    for triple in sorted(correct):
        print("  ", triple)

    print("\nMissing ground-truth triples:")
    for triple in sorted(missing):
        print("  ", triple)

    print("\nExtra triples:")
    for triple in sorted(extra):
        print("  ", triple)

    print()
