# Extraction & Verification Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, with TDD, an automated scoring harness against the manual ground truth, two deterministic pre-upload quality checks (direction/ontology, well-formedness/readability), three versioned prompt files (broad-v2, strict-tacit-v1, verify-tacit-evidence-v1), a two-step LLM verification pass, and a wiring script that composes them — all runnable and testable without a live Ollama call.

**Architecture:** New, independent modules alongside the existing pipeline (`eval/`, `verification/`, `prompts/`), none of which modify `kg_extractor.py`, `main.py`, or `neo4j_loader/`. Each module is pure/testable in isolation; the one real network call (`judge_with_ollama`) is injected via a `judge_fn` parameter everywhere it's used, so every other unit is testable with a mock.

**Tech Stack:** Python 3.11, `pytest` (new), `openpyxl` (new), `requests` (existing), stdlib `csv`/`re`/`dataclasses`/`argparse`.

**Spec:** `docs/superpowers/specs/2026-09-21-extraction-verification-design.md`

## Global Constraints

- **Zero marginal cost.** Every new LLM call goes through the local Ollama backend only (`judge_with_ollama`, default model `deepseek-r1:7b`). No OpenAI/Anthropic backend in any new module.
- **Never touch Neo4j.** No new code in this plan imports `neo4j_loader` or calls `add_triples()`.
- **Ground truth is read-only.** `eval/ground_truth.py` never writes to `KG_extraction_Marcus.xlsx`.
- **No dependency on historical hand-scored numbers.** `Prompt_Iteration_Log.xlsx`'s past Precision/Recall/F1 values are not a target for any test in this plan (see spec §7.4 for why).
- **TDD throughout.** Every task writes the test, runs it to confirm it fails, then implements.
- **This session cannot reach Ollama.** `judge_with_ollama` (Task 11) and any command in Task 13's README section are for the user to run later — nothing in this plan's automated tests depends on a live Ollama call.

---

## File structure

```
prompts/
  __init__.py
  loader.py
  extraction_broad_v2.txt
  extraction_strict_tacit_v1.txt
  verify_tacit_evidence_v1.txt
  CHANGELOG.md
verification/
  __init__.py
  text_utils.py
  predicate_directions.py
  direction_check.py
  wellformedness_check.py
  verify_pass.py
eval/
  __init__.py
  ground_truth.py
  scorer.py
  run_eval.py
run_verification_pipeline.py
tests/
  test_text_utils.py
  test_ground_truth.py
  test_scorer.py
  test_run_eval.py
  test_direction_check.py
  test_wellformedness_check.py
  test_prompts_loader.py
  test_verify_pass.py
  test_run_verification_pipeline.py
pytest.ini
requirements.txt        (modified: + openpyxl, + pytest)
README.md                (modified: + "Comparing extraction/verification configurations" section)
```

---

### Task 1: Test infrastructure

**Files:**
- Modify: `requirements.txt`
- Create: `pytest.ini`
- Create: `eval/__init__.py`
- Create: `verification/__init__.py`
- Create: `tests/test_setup.py`

**Interfaces:**
- Produces: a working `pytest` invocation from the repo root, and importable `eval`/`verification` packages, that every later task depends on.

- [ ] **Step 1: Add new dependencies**

Append to `requirements.txt`:

```
openpyxl
pytest
```

- [ ] **Step 2: Install them**

Run: `pip install -r requirements.txt`
Expected: `openpyxl` and `pytest` install successfully (both are already present in this environment from earlier prototyping, so this should be a no-op confirming versions).

- [ ] **Step 3: Add pytest config so `eval.*`/`verification.*` imports resolve**

Create `pytest.ini`:

```ini
[pytest]
pythonpath = .
```

- [ ] **Step 4: Create empty package files**

Create `eval/__init__.py` (empty file).
Create `verification/__init__.py` (empty file).

- [ ] **Step 5: Write the smoke test**

Create `tests/test_setup.py`:

```python
def test_pytest_runs():
    assert True
```

- [ ] **Step 6: Run it**

Run: `pytest tests/test_setup.py -v`
Expected: PASS (1 passed)

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pytest.ini eval/__init__.py verification/__init__.py tests/test_setup.py
git commit -m "Add pytest test infrastructure and eval/verification package skeletons"
```

---

### Task 2: `verification/text_utils.py` — CamelCase splitting

**Files:**
- Create: `verification/text_utils.py`
- Test: `tests/test_text_utils.py`

**Interfaces:**
- Produces: `split_camel_case(name: str) -> list[str]` — consumed by `eval/scorer.py` (Task 5) and `verification/wellformedness_check.py` (Task 9).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_text_utils.py`:

```python
from verification.text_utils import split_camel_case


def test_simple_camel_case():
    assert split_camel_case("GaroCommunity") == ["garo", "community"]


def test_four_word_camel_case():
    assert split_camel_case("PioneeringGaroScholarThe") == [
        "pioneering", "garo", "scholar", "the",
    ]


def test_snake_case_passthrough():
    assert split_camel_case("already_lower") == ["already", "lower"]


def test_empty_string():
    assert split_camel_case("") == []


def test_single_word():
    assert split_camel_case("Lungis") == ["lungis"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_text_utils.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verification.text_utils'`

- [ ] **Step 3: Implement**

Create `verification/text_utils.py`:

```python
"""Shared text utilities for the verification/scoring modules."""

import re

_WORD_RE = re.compile(r'[A-Z][a-z0-9]*|[a-z0-9]+')


def split_camel_case(name: str) -> list[str]:
    """Splits a CamelCase or snake_case identifier into lowercase words.

    'GaroCommunity' -> ['garo', 'community']
    'already_lower' -> ['already', 'lower']

    Known limitation: an all-uppercase acronym like 'NGOs' does not split
    cleanly (it becomes ['n', 'g', 'os']) since this project's entity-naming
    convention (see kg_extractor.py's make_extraction_prompt) rarely produces
    standalone acronyms. Token-overlap matching that uses this function is
    approximate by design; this is an accepted edge case, not a bug to chase.
    """
    if not name:
        return []
    return [word.lower() for word in _WORD_RE.findall(name) if word]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_text_utils.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add verification/text_utils.py tests/test_text_utils.py
git commit -m "Add split_camel_case shared text utility"
```

---

### Task 3: `eval/ground_truth.py` — triple and page-cell parsing helpers

**Files:**
- Create: `eval/ground_truth.py`
- Test: `tests/test_ground_truth.py`

**Interfaces:**
- Produces: `parse_triple_string(text: str) -> tuple[str, str, str] | None`, `parse_page_cell(text: str) -> tuple[frozenset[str], str | None]` — consumed later in this same task's Task 4 steps.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ground_truth.py`:

```python
from eval.ground_truth import parse_triple_string, parse_page_cell


def test_parse_triple_string_basic():
    result = parse_triple_string("(GaroCommunity)-[IS_ONE_OF]->(LargestMinorityTribes)")
    assert result == ("GaroCommunity", "IS_ONE_OF", "LargestMinorityTribes")


def test_parse_triple_string_no_match_returns_none():
    assert parse_triple_string("not a triple") is None


def test_parse_triple_string_empty_returns_none():
    assert parse_triple_string("") is None


def test_parse_page_cell_single_page():
    pages, section = parse_page_cell("page 3, Attire")
    assert pages == frozenset({"3"})
    assert section == "Attire"


def test_parse_page_cell_range():
    pages, section = parse_page_cell("page 4-5, Festival")
    assert pages == frozenset({"4", "5"})
    assert section == "Festival"


def test_parse_page_cell_empty():
    pages, section = parse_page_cell("")
    assert pages == frozenset()
    assert section is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ground_truth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.ground_truth'`

- [ ] **Step 3: Implement**

Create `eval/ground_truth.py`:

```python
"""Read-only loader for the manual ground-truth workbook (KG_extraction_Marcus.xlsx).
Never writes to the workbook. See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §7.1."""

import re
from pathlib import Path

_TRIPLE_RE = re.compile(r'\(([^)]+)\)\s*-\s*\[([^\]]+)\]\s*->\s*\(([^)]+)\)')
_PAGE_RE = re.compile(r'page\s*(\d+)(?:-(\d+))?', re.IGNORECASE)

DEFAULT_GT_PATH = str(Path(__file__).resolve().parent.parent / "KG_extraction_Marcus.xlsx")


def parse_triple_string(text: str) -> tuple[str, str, str] | None:
    """Parses '(Subject)-[PREDICATE]->(Object)' into (subject, predicate, object).
    Mirrors the core pattern kg_extractor.parse_ollama_blocks uses, so ground
    truth and pipeline output are parsed identically. Returns None if text
    doesn't match -- never raises."""
    if not text:
        return None
    match = _TRIPLE_RE.search(text)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip(), match.group(3).strip()


def parse_page_cell(text: str) -> tuple[frozenset[str], str | None]:
    """Parses a 'Page / Para' cell like 'page 4-5, Festival' into
    (frozenset({'4', '5'}), 'Festival'). Returns (frozenset(), None) if the
    cell is empty or has no recognizable page number."""
    if not text:
        return frozenset(), None
    match = _PAGE_RE.search(text)
    pages: frozenset[str] = frozenset()
    if match:
        pages = frozenset(p for p in (match.group(1), match.group(2)) if p)
    section = None
    if "," in text:
        section = text.split(",", 1)[1].strip() or None
    return pages, section
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_ground_truth.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add eval/ground_truth.py tests/test_ground_truth.py
git commit -m "Add triple-string and page-cell parsing helpers for ground truth loader"
```

---

### Task 4: `eval/ground_truth.py` — loading and joining the real workbook

**Files:**
- Modify: `eval/ground_truth.py`
- Test: `tests/test_ground_truth.py`

**Interfaces:**
- Consumes: `parse_triple_string`, `parse_page_cell`, `DEFAULT_GT_PATH` (Task 3).
- Produces: `GroundTruthTriple` dataclass, `load_sentences(xlsx_path=DEFAULT_GT_PATH) -> dict[str, tuple[frozenset[str], str | None, str]]`, `load_final_triples(xlsx_path=DEFAULT_GT_PATH) -> list[GroundTruthTriple]`, `triples_for_pages(triples, pages) -> list[GroundTruthTriple]` — consumed by `eval/run_eval.py` (Task 7).

These tests run against the real `KG_extraction_Marcus.xlsx` committed in the repo root (verified exact counts while writing this plan — see spec §9 item 2).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ground_truth.py`:

```python
from eval.ground_truth import (
    DEFAULT_GT_PATH,
    load_final_triples,
    load_sentences,
    triples_for_pages,
)


def test_load_sentences_finds_known_sentence():
    sentences = load_sentences(DEFAULT_GT_PATH)
    pages, section, text = sentences["S1"]
    assert pages == frozenset({"1"})
    assert "largest minority tribes" in text.lower()


def test_load_final_triples_total_count():
    triples = load_final_triples(DEFAULT_GT_PATH)
    assert len(triples) == 148


def test_load_final_triples_page3_subset_count():
    triples = load_final_triples(DEFAULT_GT_PATH)
    page3 = triples_for_pages(triples, ["3"])
    assert len(page3) == 23


def test_load_final_triples_rows_without_sentence_have_no_pages():
    triples = load_final_triples(DEFAULT_GT_PATH)
    no_page = [t for t in triples if not t.pages]
    assert len(no_page) == 12


def test_load_final_triples_fields_populated():
    triples = load_final_triples(DEFAULT_GT_PATH)
    first = next(t for t in triples if t.ref == "R1")
    assert first.subject == "GaroCommunity"
    assert first.predicate == "IS_ONE_OF"
    assert first.object == "LargestMinorityTribes"
    assert first.pages == frozenset({"1"})
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ground_truth.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_final_triples'`

- [ ] **Step 3: Implement**

Add to `eval/ground_truth.py` (append after the existing functions; add `openpyxl` and `dataclasses` imports at the top):

```python
from dataclasses import dataclass, field

import openpyxl

_REF_RE = re.compile(r'^[A-Za-z]+\d+$')


@dataclass(frozen=True)
class GroundTruthTriple:
    ref: str
    sentence_num: str | None
    subject: str
    predicate: str
    object: str
    pages: frozenset[str] = field(default_factory=frozenset)
    section: str | None = None
    sentence_text: str | None = None


def load_sentences(xlsx_path: str = DEFAULT_GT_PATH) -> dict[str, tuple[frozenset[str], str | None, str]]:
    """Returns {sentence_num: (pages, section, verbatim_sentence)} from the
    'Sentence Extraction' sheet. Row detection is by regex on the first cell
    (e.g. 'S1'), not a fixed row number, so leading title/instruction rows
    in the sheet are tolerated."""
    workbook = openpyxl.load_workbook(xlsx_path, data_only=True)
    sheet = workbook["Sentence Extraction"]
    result: dict[str, tuple[frozenset[str], str | None, str]] = {}
    for row in sheet.iter_rows(values_only=True):
        if not row or not row[0] or not _REF_RE.match(str(row[0])):
            continue
        sentence_num = str(row[0])
        pages, section = parse_page_cell(str(row[1]) if row[1] else "")
        sentence_text = str(row[2]).strip() if row[2] else ""
        result[sentence_num] = (pages, section, sentence_text)
    return result


def load_final_triples(xlsx_path: str = DEFAULT_GT_PATH) -> list[GroundTruthTriple]:
    """Parses the 'Final Triples' sheet, joining each row's Sentence # against
    load_sentences() for page/section/sentence text. Rows with no Sentence #,
    or one not found in the join (e.g. the 'M'-prefixed Major Findings rows),
    get empty pages / None section / None sentence_text -- not an error."""
    sentences = load_sentences(xlsx_path)
    workbook = openpyxl.load_workbook(xlsx_path, data_only=True)
    sheet = workbook["Final Triples"]
    triples: list[GroundTruthTriple] = []
    for row in sheet.iter_rows(values_only=True):
        if not row or not row[0] or not _REF_RE.match(str(row[0])):
            continue
        ref = str(row[0])
        sentence_num = str(row[1]) if row[1] else None
        parsed = parse_triple_string(str(row[2]) if row[2] else "")
        if parsed is None:
            continue
        subject, predicate, obj = parsed
        pages: frozenset[str] = frozenset()
        section: str | None = None
        sentence_text: str | None = None
        if sentence_num and sentence_num in sentences:
            pages, section, sentence_text = sentences[sentence_num]
        triples.append(GroundTruthTriple(
            ref=ref, sentence_num=sentence_num, subject=subject,
            predicate=predicate, object=obj, pages=pages,
            section=section, sentence_text=sentence_text,
        ))
    return triples


def triples_for_pages(triples: list[GroundTruthTriple], pages: list[str]) -> list[GroundTruthTriple]:
    """Returns triples whose `pages` intersects the requested set. A triple
    with empty `pages` (unknown) never matches any page filter."""
    requested = {str(page) for page in pages}
    return [t for t in triples if t.pages & requested]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_ground_truth.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add eval/ground_truth.py tests/test_ground_truth.py
git commit -m "Add ground-truth workbook loader with sentence/page joining"
```

---

### Task 5: `eval/scorer.py` — normalization, Jaccard similarity, strict/lenient matching

**Files:**
- Create: `eval/scorer.py`
- Test: `tests/test_scorer.py`

**Interfaces:**
- Consumes: `split_camel_case` from `verification.text_utils` (Task 2).
- Produces: `Triple = tuple[str, str, str]` type alias, `LENIENT_THRESHOLD` constant, `normalize`, `jaccard_similarity`, `match_strict`, `match_lenient` — consumed by Task 6's `score()`.

Per spec §7.4, the `LENIENT_THRESHOLD` value and the fixture pairs below were computed and verified by hand while writing this plan (not guessed): a real near-paraphrase pair scores 0.333, two different-fact-same-subject pairs score 0.2 and 0.222, and an exact match scores 1.0. `LENIENT_THRESHOLD = 0.3` sits between them.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scorer.py`:

```python
from eval.scorer import jaccard_similarity, match_lenient, match_strict, normalize


def test_normalize_lowercases_and_strips():
    assert normalize(" GaroCommunity ", "WEARS", " Lungis") == ("garocommunity", "wears", "lungis")


def test_match_strict_exact_after_normalization():
    a = ("GaroCommunity", "WEARS", "Lungis")
    b = ("garocommunity", "wears", "lungis")
    assert match_strict(a, b) is True


def test_match_strict_different_object_fails():
    a = ("GaroCommunity", "WEARS", "Lungis")
    b = ("GaroCommunity", "WEARS", "Sarees")
    assert match_strict(a, b) is False


def test_jaccard_identical_triples_is_one():
    a = ("GaroCommunity", "WEARS", "Lungis")
    assert jaccard_similarity(a, a) == 1.0


def test_jaccard_unrelated_triples_is_zero():
    a = ("GaroCommunity", "LIVES_IN", "Bangladesh")
    b = ("NGOs", "PROMOTE", "Education")
    assert jaccard_similarity(a, b) == 0.0


def test_match_lenient_catches_true_paraphrase():
    ground_truth = ("GaroMen", "WEARS", "Lungis")
    extracted = ("GaroCommunity", "WEAR", "Lungis")
    assert jaccard_similarity(ground_truth, extracted) > 0.3
    assert match_lenient(ground_truth, extracted) is True


def test_match_lenient_rejects_different_fact_same_subject():
    a = ("GaroCommunity", "LIVES_IN", "MountainsOfBangladesh")
    b = ("GaroCommunity", "MIGRATED_FROM", "Tibet")
    assert jaccard_similarity(a, b) < 0.3
    assert match_lenient(a, b) is False


def test_match_lenient_rejects_second_different_fact_same_subject():
    a = ("GaroCommunity", "LIVES_IN", "MountainsOfBangladesh")
    b = ("GaroCommunity", "WEARS", "Sarees")
    assert jaccard_similarity(a, b) < 0.3
    assert match_lenient(a, b) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_scorer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.scorer'`

- [ ] **Step 3: Implement**

Create `eval/scorer.py`:

```python
"""Scores extracted triples against ground truth: strict (exact) and lenient
(Jaccard token-overlap) matching. See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §7.2, §7.4."""

from verification.text_utils import split_camel_case

Triple = tuple[str, str, str]

LENIENT_THRESHOLD = 0.3


def normalize(subject: str, predicate: str, obj: str) -> Triple:
    return subject.strip().lower(), predicate.strip().lower(), obj.strip().lower()


def _tokens(triple: Triple) -> set[str]:
    subject, predicate, obj = triple
    predicate_tokens = [t for t in predicate.lower().replace("-", "_").split("_") if t]
    return set(split_camel_case(subject)) | set(predicate_tokens) | set(split_camel_case(obj))


def jaccard_similarity(a: Triple, b: Triple) -> float:
    tokens_a, tokens_b = _tokens(a), _tokens(b)
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def match_strict(a: Triple, b: Triple) -> bool:
    return normalize(*a) == normalize(*b)


def match_lenient(a: Triple, b: Triple, threshold: float = LENIENT_THRESHOLD) -> bool:
    return jaccard_similarity(a, b) >= threshold
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_scorer.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add eval/scorer.py tests/test_scorer.py
git commit -m "Add strict/lenient triple matching with calibrated Jaccard threshold"
```

---

### Task 6: `eval/scorer.py` — greedy matching and aggregate `ScoreReport`

**Files:**
- Modify: `eval/scorer.py`
- Test: `tests/test_scorer.py`

**Interfaces:**
- Consumes: `Triple`, `match_strict`, `match_lenient` (this file, Task 5).
- Produces: `ScoreReport` dataclass, `score(extracted: list[Triple], ground_truth: list[Triple], num_pages: int) -> ScoreReport` — consumed by `eval/run_eval.py` (Task 7).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scorer.py`:

```python
from eval.scorer import score


def test_score_perfect_match():
    ground_truth = [("GaroCommunity", "WEARS", "Lungis")]
    extracted = [("GaroCommunity", "WEARS", "Lungis")]
    report = score(extracted, ground_truth, num_pages=1)
    assert report.tp_strict == 1
    assert report.fp_strict == 0
    assert report.fn_strict == 0
    assert report.precision_strict == 1.0
    assert report.recall_strict == 1.0
    assert report.f1_strict == 1.0
    assert report.hallucination_rate == 0.0
    assert report.triples_per_page == 1.0


def test_score_one_hallucination():
    ground_truth = [("GaroCommunity", "WEARS", "Lungis")]
    extracted = [
        ("GaroCommunity", "WEARS", "Lungis"),
        ("Respondents", "KNOWN_ORIGIN", "Tibet"),
    ]
    report = score(extracted, ground_truth, num_pages=1)
    assert report.tp_strict == 1
    assert report.fp_strict == 1
    assert report.fn_strict == 0
    assert report.hallucination_rate == 0.5
    assert report.triples_per_page == 2.0


def test_score_lenient_catches_what_strict_misses():
    ground_truth = [("GaroMen", "WEARS", "Lungis")]
    extracted = [("GaroCommunity", "WEAR", "Lungis")]
    report = score(extracted, ground_truth, num_pages=1)
    assert report.tp_strict == 0
    assert report.tp_lenient == 1
    assert report.recall_lenient == 1.0


def test_score_no_extraction_gives_zero_precision_and_no_hallucination():
    ground_truth = [("GaroCommunity", "WEARS", "Lungis")]
    report = score([], ground_truth, num_pages=1)
    assert report.tp_strict == 0
    assert report.fn_strict == 1
    assert report.precision_strict == 0.0
    assert report.hallucination_rate == 0.0


def test_score_greedy_matching_is_one_to_one():
    # Two identical extracted triples must not both claim the single
    # ground-truth triple.
    ground_truth = [("GaroCommunity", "WEARS", "Lungis")]
    extracted = [
        ("GaroCommunity", "WEARS", "Lungis"),
        ("GaroCommunity", "WEARS", "Lungis"),
    ]
    report = score(extracted, ground_truth, num_pages=1)
    assert report.tp_strict == 1
    assert report.fp_strict == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_scorer.py -v`
Expected: FAIL with `ImportError: cannot import name 'score'`

- [ ] **Step 3: Implement**

Append to `eval/scorer.py`:

```python
from dataclasses import dataclass
from typing import Callable


def _greedy_match(extracted: list[Triple], ground_truth: list[Triple],
                   match_fn: Callable[[Triple, Triple], bool]) -> tuple[int, int, int]:
    """One-to-one greedy matching: each ground-truth triple can be claimed by
    at most one extracted triple, in extracted-list order. Not a globally
    optimal (Hungarian-algorithm) matching -- deterministic and sufficient at
    the small per-page triple counts this project works with."""
    claimed_gt: set[int] = set()
    matched_extracted = 0
    for extracted_triple in extracted:
        for gt_index, gt_triple in enumerate(ground_truth):
            if gt_index in claimed_gt:
                continue
            if match_fn(extracted_triple, gt_triple):
                claimed_gt.add(gt_index)
                matched_extracted += 1
                break
    true_positives = matched_extracted
    false_positives = len(extracted) - matched_extracted
    false_negatives = len(ground_truth) - len(claimed_gt)
    return true_positives, false_positives, false_negatives


def _precision_recall_f1(true_positives: int, false_positives: int, false_negatives: int) -> tuple[float, float, float]:
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


@dataclass
class ScoreReport:
    tp_strict: int
    fp_strict: int
    fn_strict: int
    tp_lenient: int
    fp_lenient: int
    fn_lenient: int
    precision_strict: float
    recall_strict: float
    f1_strict: float
    precision_lenient: float
    recall_lenient: float
    f1_lenient: float
    hallucination_rate: float
    triples_per_page: float


def score(extracted: list[Triple], ground_truth: list[Triple], num_pages: int) -> ScoreReport:
    tp_strict, fp_strict, fn_strict = _greedy_match(extracted, ground_truth, match_strict)
    tp_lenient, fp_lenient, fn_lenient = _greedy_match(extracted, ground_truth, match_lenient)
    precision_strict, recall_strict, f1_strict = _precision_recall_f1(tp_strict, fp_strict, fn_strict)
    precision_lenient, recall_lenient, f1_lenient = _precision_recall_f1(tp_lenient, fp_lenient, fn_lenient)
    hallucination_rate = fp_strict / len(extracted) if extracted else 0.0
    triples_per_page = len(extracted) / num_pages if num_pages else 0.0
    return ScoreReport(
        tp_strict=tp_strict, fp_strict=fp_strict, fn_strict=fn_strict,
        tp_lenient=tp_lenient, fp_lenient=fp_lenient, fn_lenient=fn_lenient,
        precision_strict=precision_strict, recall_strict=recall_strict, f1_strict=f1_strict,
        precision_lenient=precision_lenient, recall_lenient=recall_lenient, f1_lenient=f1_lenient,
        hallucination_rate=hallucination_rate, triples_per_page=triples_per_page,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_scorer.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add eval/scorer.py tests/test_scorer.py
git commit -m "Add greedy one-to-one matching and aggregate ScoreReport"
```

---

### Task 7: `eval/run_eval.py` — CLI to score a CSV and log results

**Files:**
- Create: `eval/run_eval.py`
- Test: `tests/test_run_eval.py`

**Interfaces:**
- Consumes: `DEFAULT_GT_PATH`, `load_final_triples`, `triples_for_pages` (Task 4); `score` (Task 6).
- Produces: `load_extracted(csv_path) -> list[Triple]`, `append_result(report, label, csv_path, pages, results_path)`, CLI entry point.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_eval.py`:

```python
import csv

from eval.run_eval import RESULTS_FIELDS, append_result, load_extracted
from eval.scorer import score


def test_load_extracted_reads_subject_predicate_object(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "extraction_number,paper,subject,predicate,object,source_section\n"
        "1,garo_1,GaroCommunity,WEARS,Lungis,Page 3\n",
        encoding="utf-8",
    )
    extracted = load_extracted(str(csv_path))
    assert extracted == [("GaroCommunity", "WEARS", "Lungis")]


def test_load_extracted_works_with_test_extraction_csv_shape(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "page_number,subject,predicate,object,confidence_score\n"
        "3,GaroCommunity,WEARS,Lungis,1.0\n",
        encoding="utf-8",
    )
    extracted = load_extracted(str(csv_path))
    assert extracted == [("GaroCommunity", "WEARS", "Lungis")]


def test_append_result_creates_header_on_first_write(tmp_path):
    results_path = tmp_path / "results.csv"
    report = score([("GaroCommunity", "WEARS", "Lungis")], [("GaroCommunity", "WEARS", "Lungis")], num_pages=1)

    append_result(report, "Test Label", "some.csv", "3", str(results_path))

    with open(results_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == RESULTS_FIELDS
    assert rows[1][1] == "Test Label"
    assert rows[1][2] == "some.csv"
    assert rows[1][3] == "3"


def test_append_result_appends_without_duplicate_header(tmp_path):
    results_path = tmp_path / "results.csv"
    report = score([], [("GaroCommunity", "WEARS", "Lungis")], num_pages=1)

    append_result(report, "First", "a.csv", "3", str(results_path))
    append_result(report, "Second", "b.csv", "3", str(results_path))

    with open(results_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3  # header + 2 data rows
    assert rows[1][1] == "First"
    assert rows[2][1] == "Second"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_run_eval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.run_eval'`

- [ ] **Step 3: Implement**

Create `eval/run_eval.py`:

```python
#!/usr/bin/env python3
"""CLI: score an extraction CSV against the manual ground truth.

    python -m eval.run_eval output/garo_1_page3_variantA.csv --pages 3 --label "Variant A"

Never touches Neo4j. Appends one row to eval/results.csv (creating the header
if it doesn't exist yet). See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §7.3."""

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from eval.ground_truth import DEFAULT_GT_PATH, load_final_triples, triples_for_pages
from eval.scorer import ScoreReport, Triple, score

DEFAULT_RESULTS_PATH = str(Path(__file__).resolve().parent / "results.csv")

RESULTS_FIELDS = [
    "timestamp", "label", "csv_path", "pages",
    "tp_strict", "fp_strict", "fn_strict",
    "tp_lenient", "fp_lenient", "fn_lenient",
    "precision_strict", "recall_strict", "f1_strict",
    "precision_lenient", "recall_lenient", "f1_lenient",
    "hallucination_rate", "triples_per_page",
]


def load_extracted(csv_path: str) -> list[Triple]:
    """Reads subject/predicate/object columns from an extraction CSV. Works
    with either output shape the pipeline produces (test_extraction.py's
    page_number/subject/predicate/object/confidence_score, or main.py's
    extraction_number/paper/subject/predicate/object/source_section/...)
    since only the three shared column names are read."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [(row["subject"], row["predicate"], row["object"]) for row in reader]


def append_result(report: ScoreReport, label: str, csv_path: str, pages: str,
                   results_path: str = DEFAULT_RESULTS_PATH) -> None:
    results_file = Path(results_path)
    write_header = not results_file.exists()
    with open(results_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(RESULTS_FIELDS)
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            label, csv_path, pages,
            report.tp_strict, report.fp_strict, report.fn_strict,
            report.tp_lenient, report.fp_lenient, report.fn_lenient,
            report.precision_strict, report.recall_strict, report.f1_strict,
            report.precision_lenient, report.recall_lenient, report.f1_lenient,
            report.hallucination_rate, report.triples_per_page,
        ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Score an extraction CSV against the manual ground truth.")
    parser.add_argument("csv_path")
    parser.add_argument("--pages", required=True, help="Comma-separated page numbers, e.g. '3' or '1,4,5'")
    parser.add_argument("--label", required=True, help="Name for this run, e.g. 'Variant A (broad-v2)'")
    parser.add_argument("--gt-path", default=DEFAULT_GT_PATH)
    parser.add_argument("--results-path", default=DEFAULT_RESULTS_PATH)
    args = parser.parse_args()

    pages = [p.strip() for p in args.pages.split(",") if p.strip()]
    extracted = load_extracted(args.csv_path)
    ground_truth = triples_for_pages(load_final_triples(args.gt_path), pages)
    gt_triples: list[Triple] = [(t.subject, t.predicate, t.object) for t in ground_truth]

    report = score(extracted, gt_triples, num_pages=len(pages))
    append_result(report, args.label, args.csv_path, args.pages, args.results_path)

    print(
        f"{args.label}: TP-strict={report.tp_strict} TP-lenient={report.tp_lenient} "
        f"P/R/F1(strict)={report.precision_strict:.2f}/{report.recall_strict:.2f}/{report.f1_strict:.2f} "
        f"hallucination_rate={report.hallucination_rate:.2f} triples_per_page={report.triples_per_page:.1f}"
    )
    print(f"Appended to {args.results_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_run_eval.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Manual smoke check against real data (not an automated test)**

Run: `python -m eval.run_eval output/garo_1_page3_variantbaseline.csv --pages 3 --label "manual smoke check"`
Expected: prints a plausible-looking report line and "Appended to eval/results.csv"; does not crash. Then delete the smoke-test row/file so it doesn't get committed as fake data:

Run: `rm eval/results.csv` (Windows: `del eval\results.csv`)

- [ ] **Step 6: Commit**

```bash
git add eval/run_eval.py tests/test_run_eval.py
git commit -m "Add eval CLI to score extraction CSVs and log results"
```

---

### Task 8: `verification/direction_check.py` — deterministic direction/ontology check

**Files:**
- Create: `verification/predicate_directions.py`
- Create: `verification/direction_check.py`
- Test: `tests/test_direction_check.py`

**Interfaces:**
- Produces: `DIRECTIONAL_PREDICATES` dict, `DirectionResult` dataclass, `check_direction(subject, predicate, obj) -> DirectionResult` — consumed by `run_verification_pipeline.py` (Task 12).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_direction_check.py`:

```python
from verification.direction_check import check_direction


def test_correctly_directed_prohibits_not_flagged():
    result = check_direction("VillageCouncilRule", "PROHIBITS", "FishingInTheArea")
    assert result.flagged is False


def test_reversed_prohibits_is_flagged():
    result = check_direction("FishingArea", "PROHIBITS", "VillageCouncilRule")
    assert result.flagged is True
    assert "PROHIBITS" in result.reason


def test_reversed_governs_is_flagged():
    result = check_direction("LandDispute", "GOVERNS", "ClanCouncil")
    assert result.flagged is True


def test_unknown_predicate_never_flagged():
    result = check_direction("GaroCommunity", "WEARS", "Lungis")
    assert result.flagged is False
    assert result.reason is None


def test_ambiguous_case_not_flagged():
    # Neither side matches the lexicon's keyword shape at all -- silence,
    # not a guess.
    result = check_direction("SomeGroup", "REQUIRES", "SomethingElse")
    assert result.flagged is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_direction_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verification.direction_check'`

- [ ] **Step 3: Implement**

Create `verification/predicate_directions.py`:

```python
"""Curated predicate-direction lexicon for the deterministic direction/ontology
check (verification/direction_check.py). Predicates not listed here are never
flagged -- silence, not a guess. Seeded from predicates observed in the ground
truth workbook and the strict extraction prompt's own worked examples; extend
as real predicates are observed in new runs. See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §6.1."""

DIRECTIONAL_PREDICATES: dict[str, dict[str, list[str]]] = {
    "PROHIBITS": {
        "subject_keywords": ["rule", "law", "custom", "taboo", "tradition", "authority", "council"],
        "object_keywords": ["fishing", "hunting", "activity", "area", "practice", "place"],
    },
    "REQUIRES": {
        "subject_keywords": ["ritual", "ceremony", "festival", "custom", "practice", "tradition", "marriage"],
        "object_keywords": ["permission", "approval", "payment", "offering", "preparation", "materials", "consent"],
    },
    "GOVERNS": {
        "subject_keywords": ["council", "chief", "elder", "authority", "system", "clan", "institution"],
        "object_keywords": ["land", "property", "inheritance", "marriage", "dispute", "community"],
    },
    "TEACHES": {
        "subject_keywords": ["elder", "parent", "teacher", "mother", "father", "community", "school"],
        "object_keywords": ["skill", "craft", "language", "tradition", "knowledge", "practice"],
    },
}
```

Create `verification/direction_check.py`:

```python
"""Deterministic direction/ontology check: flags a triple whose Subject/Object
keyword shape looks reversed against a curated predicate-direction lexicon.
No LLM call, flag-only (never deletes). See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §6.1."""

from dataclasses import dataclass

from verification.predicate_directions import DIRECTIONAL_PREDICATES


@dataclass
class DirectionResult:
    flagged: bool
    reason: str | None = None


def _contains_any(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in keywords)


def check_direction(subject: str, predicate: str, obj: str) -> DirectionResult:
    entry = DIRECTIONAL_PREDICATES.get(predicate.strip().upper())
    if entry is None:
        return DirectionResult(flagged=False)

    subject_looks_like_object = _contains_any(subject, entry["object_keywords"])
    object_looks_like_subject = _contains_any(obj, entry["subject_keywords"])

    if subject_looks_like_object and object_looks_like_subject:
        return DirectionResult(
            flagged=True,
            reason=(
                f"{predicate}: subject '{subject}' matches expected object-side "
                f"keywords and object '{obj}' matches expected subject-side "
                f"keywords -- direction looks reversed."
            ),
        )
    return DirectionResult(flagged=False)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_direction_check.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add verification/predicate_directions.py verification/direction_check.py tests/test_direction_check.py
git commit -m "Add deterministic predicate-direction check"
```

---

### Task 9: `verification/wellformedness_check.py` — deterministic readability gate

**Files:**
- Create: `verification/wellformedness_check.py`
- Test: `tests/test_wellformedness_check.py`

**Interfaces:**
- Consumes: `split_camel_case` (Task 2).
- Produces: `WellformednessResult` dataclass, `check_wellformedness(subject, predicate, obj) -> WellformednessResult` — consumed by `run_verification_pipeline.py` (Task 12).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_wellformedness_check.py`:

```python
from verification.wellformedness_check import check_wellformedness


def test_clean_triple_not_flagged():
    result = check_wellformedness("GaroCommunity", "WEARS", "Lungis")
    assert result.flagged is False
    assert result.reasons == []


def test_dangling_word_appositive_bug_is_flagged():
    # Real, previously-observed case: subject_specificity.py's own comments
    # document this exact mis-chunked-appositive entity name.
    result = check_wellformedness("PioneeringGaroScholarThe", "WROTE", "Book")
    assert result.flagged is True
    assert any("dangling" in reason for reason in result.reasons)


def test_oversized_entity_is_flagged():
    result = check_wellformedness(
        "VeryOldTraditionalGaroHouseholdStructure", "HAS_FEATURE", "ThatchedRoof"
    )
    assert result.flagged is True
    assert any("6 words" in reason for reason in result.reasons)


def test_overlong_predicate_is_flagged():
    result = check_wellformedness(
        "GaroCommunity", "IS_USED_IN_THE_TRADITIONAL_CONTEXT_OF", "Ceremony"
    )
    assert result.flagged is True
    assert any("segments" in reason for reason in result.reasons)


def test_simple_predicate_not_flagged():
    result = check_wellformedness("GaroCommunity", "HAS_PROFESSION", "Farmer")
    assert result.flagged is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_wellformedness_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verification.wellformedness_check'`

- [ ] **Step 3: Implement**

Create `verification/wellformedness_check.py`:

```python
"""Deterministic well-formedness/readability check: flags (never deletes) a
triple whose Subject, Predicate, or Object looks like a mis-split sentence
fragment rather than a clean entity/relationship name. No LLM call -- purely
structural/shape checks; semantic garbling is instead caught by the strict
prompt's readability rule and the verify pass's third question. See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §6.2."""

from dataclasses import dataclass, field

from verification.text_utils import split_camel_case

MAX_ENTITY_WORDS = 4
MAX_PREDICATE_WORDS = 3
DANGLING_LEADING_WORDS = {"the", "a", "an", "of", "in", "on", "at", "and", "or"}


@dataclass
class WellformednessResult:
    flagged: bool
    reasons: list[str] = field(default_factory=list)


def _check_entity(label: str, name: str) -> list[str]:
    words = split_camel_case(name)
    reasons = []
    if len(words) > MAX_ENTITY_WORDS:
        reasons.append(f"{label} '{name}' has {len(words)} words (max {MAX_ENTITY_WORDS})")
    if words and (words[0] in DANGLING_LEADING_WORDS or words[-1] in DANGLING_LEADING_WORDS):
        reasons.append(f"{label} '{name}' starts or ends on a dangling word")
    return reasons


def check_wellformedness(subject: str, predicate: str, obj: str) -> WellformednessResult:
    reasons = _check_entity("Subject", subject) + _check_entity("Object", obj)

    predicate_segments = [segment for segment in predicate.strip().split("_") if segment]
    if len(predicate_segments) > MAX_PREDICATE_WORDS:
        reasons.append(
            f"Predicate '{predicate}' has {len(predicate_segments)} segments "
            f"(max {MAX_PREDICATE_WORDS}) -- looks like a clause, not a relation name"
        )

    return WellformednessResult(flagged=bool(reasons), reasons=reasons)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_wellformedness_check.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add verification/wellformedness_check.py tests/test_wellformedness_check.py
git commit -m "Add deterministic well-formedness/readability check"
```

---

### Task 10: Versioned prompt files and loader

**Files:**
- Create: `prompts/__init__.py`
- Create: `prompts/loader.py`
- Create: `prompts/extraction_broad_v2.txt`
- Create: `prompts/extraction_strict_tacit_v1.txt`
- Create: `prompts/verify_tacit_evidence_v1.txt`
- Create: `prompts/CHANGELOG.md`
- Test: `tests/test_prompts_loader.py`

**Interfaces:**
- Produces: `load_prompt_template(name: str) -> str`, `load_prompt(name: str) -> Callable[[str], str]` — `load_prompt_template` is consumed by `verification/verify_pass.py` (Task 11); `load_prompt` is what a future harness script (run outside this plan, per spec §10) would use for the two extraction prompts.

Prompt placeholders use literal `{token}` text replaced with `str.replace()`, not `str.format()` — `verify_tacit_evidence_v1.txt` displays a literal JSON schema to the model, which would require escaping every brace under `.format()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prompts_loader.py`:

```python
from prompts.loader import load_prompt, load_prompt_template


def test_load_prompt_template_reads_real_file():
    text = load_prompt_template("extraction_broad_v2")
    assert "{passage}" in text
    assert "Garo" in text


def test_load_prompt_fills_in_passage():
    build_prompt = load_prompt("extraction_broad_v2")
    result = build_prompt("Some passage text.")
    assert "Some passage text." in result
    assert "{passage}" not in result


def test_load_prompt_strict_tacit_has_no_leftover_placeholder():
    build_prompt = load_prompt("extraction_strict_tacit_v1")
    result = build_prompt("Example passage.")
    assert "Example passage." in result
    assert "{passage}" not in result


def test_verify_prompt_template_has_expected_placeholders():
    text = load_prompt_template("verify_tacit_evidence_v1")
    for placeholder in ("{source_sentence}", "{subject}", "{predicate}", "{object}"):
        assert placeholder in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_prompts_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prompts'`

- [ ] **Step 3: Implement**

Create `prompts/__init__.py` (empty file).

Create `prompts/loader.py`:

```python
"""Loads versioned prompt template files. See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §4."""

from pathlib import Path
from typing import Callable

PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt_template(name: str) -> str:
    """Returns the raw template text for prompts/<name>.txt. `name` excludes
    the .txt extension, e.g. 'extraction_strict_tacit_v1'."""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def load_prompt(name: str) -> Callable[[str], str]:
    """For the single-placeholder extraction prompts: returns a function that
    fills in the passage text via plain string replacement (not str.format,
    since some templates display literal JSON braces to the model)."""
    template = load_prompt_template(name)

    def build_prompt(passage: str) -> str:
        return template.replace("{passage}", passage)

    return build_prompt
```

Create `prompts/extraction_broad_v2.txt`:

```
You are a knowledge graph extraction assistant. You will be provided with a passage from an academic research paper.

Read the passage. Identify every factual claim, relationship, practice, belief, observation, or piece of knowledge from this passage, in the Garo / Mandi cultural context. This passage may come from any part of the paper -- introduction, demographics, attire, food, religion, festivals, health, household life, occupation, or any other section -- so do not assume in advance which topic it covers.

Output your answer immediately as a sequence of Cypher comment blocks. Do not include any reasoning, planning, or <think> content, and do not write anything before the first block -- your entire response must consist only of comment blocks in this exact format:

// PASSAGE: (Subject)-[PREDICATE]->(Object)
// SENTENCE REF: <exact sentence from the paper this was drawn from>
// SOURCE: <paper title placeholder>

Strict rules for the PASSAGE line:
- It MUST be written ONLY as (Subject)-[PREDICATE]->(Object). Never write a full sentence, paraphrase, or description on the PASSAGE line -- that line is a structured triple, not prose.
- Subject and Object must be short noun phrases (1-4 words) in CamelCase with no spaces, e.g. (MandiLanguage), (GaroCommunity).
- Predicate must be UPPER_CASE_WITH_UNDERSCORES ONLY -- no lowercase letters, no spaces, no mixed case. For example, write IS_USED_IN, never "IS USED IN"; write WEARS, never "WE WEAR"; write HAS_FAMILY_STRUCTURE, never "HAS_FamilyStructure". A predicate containing a space or a lowercase word is always wrong -- rewrite it before outputting the block.
- Choose the Subject at the level of specificity the sentence itself actually supports -- neither more nor less. If the sentence names a specific subgroup, item, individual, organization, ritual, or role, use that specific entity as the Subject. If the sentence instead makes a general statement about the community as a whole, GaroPeople or GaroCommunity IS the correct Subject -- do not force a narrower entity onto a general statement, and do not default to a broad community-level noun when the sentence clearly names something narrower.
- If a sentence lists multiple values for the same relationship (e.g. multiple professions, locations, languages, foods, or beliefs), output ONE SEPARATE triple per value. Never combine multiple values into a single comma-separated Object -- e.g. write (GaroCommunity)-[HAS_PROFESSION]->(Teacher) and (GaroCommunity)-[HAS_PROFESSION]->(Farmer) as two blocks, not one block with (Teacher, Farmer). If you decide not to extract something because it is a duplicate, simply skip it -- never bundle it into another block instead.
- Do not decide in advance what topics or domains to look for -- extract everything factual the passage contains about the Garo/Mandi community's culture, language, history, beliefs, practices, and lived experience, whatever section of the paper it comes from.
- Each PASSAGE line must be traceable to a specific sentence, quoted exactly in SENTENCE REF. If you cannot find an exact sentence, do not output a block for that content at all.

Skip entirely -- do not output a block for any of the following:
- Bibliographic references, author citations, journal titles, page numbers, or keyword lists.
- Anything describing the research process itself rather than the community: sample sizes, participant/respondent counts or demographics, what participants or respondents were asked, told, or observed to say, how they were classified or coded (e.g. classification schemes, occupational codes), interview or data collection methods, data analysis procedures, or any subjective assessment the researchers made about participants (e.g. calling them vulnerable, hesitant, willing, or reluctant). "Respondents" or "participants" must never appear as a Subject or Object. Only extract facts about the Garo/Mandi community itself, never facts about how the paper studied them or who was surveyed.

Output only the formatted comment blocks. No explanation, no prose, no extra text, and nothing before the first "// PASSAGE:" line.

Passage:
{passage}
```

Create `prompts/extraction_strict_tacit_v1.txt`:

```
You are a knowledge graph extraction assistant working on a project that preserves TACIT and CULTURAL knowledge of the Garo/Mandi Indigenous community of Bangladesh. You will be provided with a passage from an academic research paper.

WHAT COUNTS AS TACIT KNOWLEDGE FOR THIS PROJECT:
Tacit knowledge is unwritten, experience-based, practice-embedded knowledge -- how something is done, why it matters, or what it means to the people who live it -- as opposed to demographic facts, bibliographic facts, or statements about the research process itself. It is knowledge a community member would recognize as "how we do things" or "what we believe," not a statistic about the community.

Examples of TACIT KNOWLEDGE worth extracting (do output triples like these):
- (GaroMen)-[WEARS]->(Lungis) -- a lived clothing practice.
- (GaroCommunity)-[PRACTICES]->(MatrilinealInheritance) -- a social/cultural practice.
- (GaroCommunity)-[BELIEVES_IN]->(Sangsarek) -- a belief system.
- (GaroCommunity)-[CELEBRATES]->(WangalaFestival) -- a cultural practice/event.
- (GaroWomen)-[PREPARE]->(FermentedRiceBeer) -- a craft/practice.
- (GaroCommunity)-[FACES]->(LandOwnershipDisputes) -- a lived challenge tied to practice, not a research finding about the study.

Examples that are NOT tacit knowledge (do NOT output triples like these):
- (GaroCommunity)-[HAS_POPULATION]->(TwoHundredThousand) -- a demographic statistic, not lived/experiential knowledge.
- (Billah2023)-[PUBLISHED_IN]->(JournalOfBangladeshStudies) -- a bibliographic fact about the paper, not about the community.
- (Respondents)-[WERE_ASKED_ABOUT]->(FamilyStructure) -- describes the research process, not the community.
- (Sample)-[HAD_SIZE]->(FiftyParticipants) -- a methodology fact.
- (GaroCommunity)-[MAY_HAVE]->(UnclearOrigin) -- too vague/unverifiable to be a usable fact.
- (Researchers)-[CONCLUDED]->(FurtherStudyNeeded) -- a statement about the study, not the community.

If a passage contains nothing that clearly clears this bar, output nothing for it -- it is better to miss a fact than to store an incorrect, vague, or off-topic one. Do not force a weak or borderline candidate into a triple just to have something to output.

READABILITY RULE: before outputting a block, read it back as "(Subject) predicate (Object)". If the result would be confusing or meaningless to someone with no other context, do not output it.

Output your answer immediately as a sequence of Cypher comment blocks. Do not include any reasoning, planning, or <think> content, and do not write anything before the first block -- your entire response must consist only of comment blocks in this exact format:

// PASSAGE: (Subject)-[PREDICATE]->(Object)
// SENTENCE REF: <exact sentence from the paper this was drawn from>
// SOURCE: <paper title placeholder>

Strict rules for the PASSAGE line:
- It MUST be written ONLY as (Subject)-[PREDICATE]->(Object). Never write a full sentence, paraphrase, or description on the PASSAGE line -- that line is a structured triple, not prose.
- Subject and Object must be short noun phrases (1-4 words) in CamelCase with no spaces, e.g. (MandiLanguage), (GaroCommunity).
- Predicate must be UPPER_CASE_WITH_UNDERSCORES ONLY -- no lowercase letters, no spaces, no mixed case.
- Choose the Subject at the level of specificity the sentence itself actually supports -- neither more nor less. If the sentence names a specific subgroup, item, individual, organization, ritual, or role, use that specific entity as the Subject. If the sentence instead makes a general statement about the community as a whole, GaroPeople or GaroCommunity IS the correct Subject.
- If a sentence lists multiple values for the same relationship, output ONE SEPARATE triple per value. Never combine multiple values into a single comma-separated Object.
- Each PASSAGE line must be traceable to a specific sentence, quoted exactly in SENTENCE REF. If you cannot find an exact sentence, do not output a block for that content at all.

Output only the formatted comment blocks. No explanation, no prose, no extra text, and nothing before the first "// PASSAGE:" line.

Passage:
{passage}
```

Create `prompts/verify_tacit_evidence_v1.txt`:

```
You are checking one candidate entry for a knowledge graph about the Garo/Mandi community's tacit and cultural knowledge.

Source sentence:
"""{source_sentence}"""

Candidate triple: ({subject})-[{predicate}]->({object})

Answer three questions about this triple, then give one combined decision:

1. EVIDENCE: Is this relationship actually stated or clearly implied by the source sentence? (Not: is it true in general -- only: does THIS sentence support it.)
2. TACIT KNOWLEDGE: Is this genuine tacit/cultural knowledge -- unwritten, experience-based, practice-embedded knowledge about how the community lives, believes, or practices -- rather than a demographic statistic, a bibliographic fact, or a description of the research process itself (sample sizes, what respondents were asked/told, interview methods, or anything about "the study" or "the researchers")?
3. READABILITY: Read the triple on its own, with no other context, as "(Subject) predicate (Object)". Would this make sense to someone who has never seen the source sentence? A triple can be evidenced and tacit but still fail this if the entity names are garbled, the predicate doesn't read as a real relationship, or the pairing is confusing out of context.

If any answer is no, the triple does not belong in this graph, even if the others are yes.

Respond with ONLY a JSON object, no other text:
{"decision": "keep" or "reject", "confidence": <float 0.0-1.0>, "reason": "<one short sentence naming which question failed, if any>"}

confidence close to 1.0 means all three questions are clearly yes. confidence close to 0.0 means at least one is clearly no.
```

Create `prompts/CHANGELOG.md`:

```markdown
# Prompt changelog

## extraction_broad_v2 (2026-09-21)

Copy of the live `kg_extractor.make_extraction_prompt()` prompt (documented there as
"PR008 / Variant A round 4"), with one change: the opening framing "identify every ...
knowledge about the Garo/Mandi community" is reworded to "identify every ... knowledge
from this passage, in the Garo/Mandi cultural context." The domain scope is unchanged;
the implicit "the subject of every fact is the community" framing is removed, since it
actively worked against the prompt's own later instruction to match the sentence's own
specificity (see design spec §4 and §2 for the hub-collapse evidence this responds to).

## extraction_strict_tacit_v1 (2026-09-21)

New. Directly implements Tanjila's "try a strict tacit-only prompt" suggestion: an
explicit tacit-knowledge definition, worked examples and non-examples, and a rule to
output nothing rather than force a weak triple ("better to miss than to store wrong").
Also carries the readability rule that responds to the observed unreadable-triple
problem in the live Neo4j graph (see design spec §1.1 goal 3, §4).

## verify_tacit_evidence_v1 (2026-09-21)

New. Second-step verification prompt for the two-step extract-then-verify pipeline
configuration. Asks evidence, tacit-knowledge, and readability together in one call
(mirroring `pruner/llm_judge.py`'s combined-question pattern), so the two-step design
costs exactly 2 LLM calls per candidate triple (extract, verify), not 3 or 4 (see
design spec §5, §1.2 zero-cost constraint).
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_prompts_loader.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add prompts/
git commit -m "Add versioned extraction/verification prompt files and loader"
```

---

### Task 11: `verification/verify_pass.py` — two-step LLM verification

**Files:**
- Create: `verification/verify_pass.py`
- Test: `tests/test_verify_pass.py`

**Interfaces:**
- Consumes: `load_prompt_template` (Task 10).
- Produces: `VerifyResult` dataclass, `VERIFY_LOW_THRESHOLD`, `VERIFY_HIGH_THRESHOLD` constants, `verify_triple(subject, predicate, obj, source_sentence, judge_fn) -> VerifyResult`, `judge_with_ollama(subject, predicate, obj, source_sentence, model="deepseek-r1:7b") -> tuple[str, float, str]` — consumed by `run_verification_pipeline.py` (Task 12).

`judge_with_ollama` is the real, Ollama-only backend (zero-cost constraint, spec §1.2) — it is not unit tested here since it requires a live Ollama call, consistent with how `pruner/llm_judge.py`'s own real backends aren't unit tested either. It gets exercised manually later (spec §10).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_verify_pass.py`:

```python
from verification.verify_pass import (
    VERIFY_HIGH_THRESHOLD,
    VERIFY_LOW_THRESHOLD,
    _parse_judge_response,
    verify_triple,
)


def test_parse_judge_response_valid_json():
    text = '{"decision": "keep", "confidence": 0.85, "reason": "well supported"}'
    decision, confidence, reason = _parse_judge_response(text)
    assert decision == "keep"
    assert confidence == 0.85
    assert reason == "well supported"


def test_parse_judge_response_json_embedded_in_prose():
    text = 'Sure, here is my answer: {"decision": "reject", "confidence": 0.1, "reason": "not evidenced"}'
    decision, confidence, reason = _parse_judge_response(text)
    assert decision == "reject"
    assert confidence == 0.1


def test_parse_judge_response_unparseable_falls_back_to_reject():
    decision, confidence, reason = _parse_judge_response("no json here at all")
    assert decision == "reject"
    assert confidence == 0.0
    assert reason == "unparseable_judge_response"


def test_verify_triple_high_confidence_keeps():
    def fake_judge(subject, predicate, obj, source_sentence):
        return "keep", 0.9, "clearly supported"

    result = verify_triple("GaroCommunity", "WEARS", "Lungis", "Garo men wear lungis.", fake_judge)
    assert result.band == "keep"
    assert result.confidence == 0.9


def test_verify_triple_low_confidence_rejects():
    def fake_judge(subject, predicate, obj, source_sentence):
        return "reject", 0.1, "not evidenced"

    result = verify_triple("Respondents", "KNOWN_ORIGIN", "Tibet", "Some respondents said Tibet.", fake_judge)
    assert result.band == "reject"


def test_verify_triple_mid_confidence_goes_to_review():
    def fake_judge(subject, predicate, obj, source_sentence):
        return "reject", 0.5, "borderline tacit knowledge"

    result = verify_triple("GaroCommunity", "ATE", "Rice", "Some claim about rice.", fake_judge)
    assert result.band == "review"


def test_thresholds_are_ordered():
    assert VERIFY_LOW_THRESHOLD < VERIFY_HIGH_THRESHOLD
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_verify_pass.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'verification.verify_pass'`

- [ ] **Step 3: Implement**

Create `verification/verify_pass.py`:

```python
"""Two-step verification pass: checks one candidate triple for evidence,
tacit-ness, and readability (prompts/verify_tacit_evidence_v1.txt) via a
pluggable judge_fn. The real backend is Ollama-only (zero marginal cost --
see docs/superpowers/specs/2026-09-21-extraction-verification-design.md
§1.2, §5)."""

import json
import os
import re
from dataclasses import dataclass
from typing import Callable

import requests

from prompts.loader import load_prompt_template

VERIFY_LOW_THRESHOLD = 0.35
VERIFY_HIGH_THRESHOLD = 0.7

OLLAMA_VERIFY_URL = os.environ.get("OLLAMA_VERIFY_URL", "http://localhost:11434/api/generate")

JudgeFn = Callable[[str, str, str, str], tuple[str, float, str]]


@dataclass
class VerifyResult:
    band: str  # "keep", "review", or "reject"
    decision: str
    confidence: float
    reason: str


def _parse_judge_response(text: str) -> tuple[str, float, str]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return "reject", 0.0, "unparseable_judge_response"
    try:
        data = json.loads(match.group(0))
        return (
            str(data.get("decision", "reject")),
            float(data.get("confidence", 0.0)),
            str(data.get("reason", "")),
        )
    except (ValueError, json.JSONDecodeError):
        return "reject", 0.0, "unparseable_judge_response"


def judge_with_ollama(subject: str, predicate: str, obj: str, source_sentence: str,
                       model: str = "deepseek-r1:7b") -> tuple[str, float, str]:
    """Real backend -- local Ollama only, no paid API. Not unit tested (requires
    a live Ollama call); exercised manually per spec §10."""
    template = load_prompt_template("verify_tacit_evidence_v1")
    prompt = (
        template.replace("{source_sentence}", source_sentence)
        .replace("{subject}", subject)
        .replace("{predicate}", predicate)
        .replace("{object}", obj)
    )
    response = requests.post(
        OLLAMA_VERIFY_URL,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=60,
    )
    response.raise_for_status()
    return _parse_judge_response(response.json().get("response", ""))


def verify_triple(subject: str, predicate: str, obj: str, source_sentence: str,
                   judge_fn: JudgeFn) -> VerifyResult:
    decision, confidence, reason = judge_fn(subject, predicate, obj, source_sentence)
    if confidence < VERIFY_LOW_THRESHOLD:
        band = "reject"
    elif confidence >= VERIFY_HIGH_THRESHOLD:
        band = "keep"
    else:
        band = "review"
    return VerifyResult(band=band, decision=decision, confidence=confidence, reason=reason)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_verify_pass.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add verification/verify_pass.py tests/test_verify_pass.py
git commit -m "Add two-step LLM verification pass with pluggable Ollama-only backend"
```

---

### Task 12: `run_verification_pipeline.py` — wiring script

**Files:**
- Create: `run_verification_pipeline.py`
- Test: `tests/test_run_verification_pipeline.py`

**Interfaces:**
- Consumes: `check_direction` (Task 8), `check_wellformedness` (Task 9), `verify_triple`, `judge_with_ollama` (Task 11).
- Produces: `run(csv_path, run_verify, run_direction, run_wellformed, judge_fn=judge_with_ollama) -> dict`, CLI entry point.

Never imports `neo4j_loader`, never calls `add_triples()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_verification_pipeline.py`:

```python
import csv

from run_verification_pipeline import run


def _fake_judge(subject, predicate, obj, source_sentence):
    if subject == "GaroCommunity" and predicate == "ATE":
        return "reject", 0.5, "borderline tacit knowledge"
    return "keep", 0.9, "fine"


def test_run_verification_pipeline_writes_expected_outputs(tmp_path):
    csv_path = tmp_path / "sample.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["GaroCommunity", "WEARS", "Lungis", "Garo men wear lungis."])
        writer.writerow(["FishingArea", "PROHIBITS", "VillageCouncilRule", "The rule prohibits fishing."])
        writer.writerow(["PioneeringGaroScholarThe", "WROTE", "Book", "A scholar wrote a book."])
        writer.writerow(["GaroCommunity", "ATE", "Rice", "Some claim about rice."])

    summary = run(
        str(csv_path), run_verify=True, run_direction=True, run_wellformed=True,
        judge_fn=_fake_judge,
    )

    assert summary == {
        "refined": 3,
        "reviewed_out": 1,
        "direction_flags": 1,
        "wellformedness_flags": 1,
    }

    assert (tmp_path / "sample_refined.csv").exists()
    assert (tmp_path / "sample_reviewed_out.csv").exists()
    assert (tmp_path / "sample_direction_flags.csv").exists()
    assert (tmp_path / "sample_wellformedness_flags.csv").exists()

    with open(tmp_path / "sample_reviewed_out.csv", newline="", encoding="utf-8") as f:
        reviewed_rows = list(csv.DictReader(f))
    assert reviewed_rows[0]["subject"] == "GaroCommunity"
    assert reviewed_rows[0]["predicate"] == "ATE"


def test_run_verification_pipeline_without_verify_keeps_all_flagged_rows_too(tmp_path):
    csv_path = tmp_path / "sample2.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["FishingArea", "PROHIBITS", "VillageCouncilRule", "The rule prohibits fishing."])

    summary = run(str(csv_path), run_verify=False, run_direction=True, run_wellformed=False)

    # Flagging never removes a triple from refined -- flag-only, never auto-delete.
    assert summary["refined"] == 1
    assert summary["direction_flags"] == 1
    assert not (tmp_path / "sample2_reviewed_out.csv").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_run_verification_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'run_verification_pipeline'`

- [ ] **Step 3: Implement**

Create `run_verification_pipeline.py`:

```python
#!/usr/bin/env python3
"""Takes an already-produced extraction CSV and optionally runs the verify
pass, direction check, and/or well-formedness check on it. Never imports
neo4j_loader, never calls add_triples(). See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §7.5.

    python run_verification_pipeline.py output/garo_1_page3_variantA.csv \\
        --direction-check --wellformedness-check --verify
"""

import argparse
import csv
from pathlib import Path

from verification.direction_check import check_direction
from verification.verify_pass import JudgeFn, judge_with_ollama, verify_triple
from verification.wellformedness_check import check_wellformedness


def load_rows(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _sentence_for_row(row: dict) -> str:
    return row.get("sentence_ref") or row.get("passage") or ""


def write_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run(csv_path: str, run_verify: bool, run_direction: bool, run_wellformed: bool,
        judge_fn: JudgeFn = judge_with_ollama) -> dict:
    rows = load_rows(csv_path)
    fieldnames = list(rows[0].keys()) if rows else ["subject", "predicate", "object"]

    refined: list[dict] = []
    reviewed_out: list[dict] = []
    direction_flags: list[dict] = []
    wellformedness_flags: list[dict] = []

    for row in rows:
        subject, predicate, obj = row["subject"], row["predicate"], row["object"]

        if run_direction:
            direction_result = check_direction(subject, predicate, obj)
            if direction_result.flagged:
                flagged_row = dict(row)
                flagged_row["flag_reason"] = direction_result.reason or ""
                direction_flags.append(flagged_row)

        if run_wellformed:
            wellformedness_result = check_wellformedness(subject, predicate, obj)
            if wellformedness_result.flagged:
                flagged_row = dict(row)
                flagged_row["flag_reason"] = "; ".join(wellformedness_result.reasons)
                wellformedness_flags.append(flagged_row)

        if run_verify:
            result = verify_triple(subject, predicate, obj, _sentence_for_row(row), judge_fn)
            if result.band == "keep":
                refined.append(row)
            elif result.band == "review":
                reviewed_row = dict(row)
                reviewed_row["verify_reason"] = result.reason
                reviewed_row["verify_confidence"] = result.confidence
                reviewed_out.append(reviewed_row)
            # "reject" band: dropped, not written anywhere -- same as main.py's
            # existing validation gate, rejection is implicit via absence.
        else:
            refined.append(row)

    stem = Path(csv_path).stem
    out_dir = Path(csv_path).parent
    write_rows(out_dir / f"{stem}_refined.csv", fieldnames, refined)
    if reviewed_out:
        write_rows(
            out_dir / f"{stem}_reviewed_out.csv",
            fieldnames + ["verify_reason", "verify_confidence"], reviewed_out,
        )
    if direction_flags:
        write_rows(out_dir / f"{stem}_direction_flags.csv", fieldnames + ["flag_reason"], direction_flags)
    if wellformedness_flags:
        write_rows(out_dir / f"{stem}_wellformedness_flags.csv", fieldnames + ["flag_reason"], wellformedness_flags)

    return {
        "refined": len(refined),
        "reviewed_out": len(reviewed_out),
        "direction_flags": len(direction_flags),
        "wellformedness_flags": len(wellformedness_flags),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run verification/direction/well-formedness checks on an extraction CSV."
    )
    parser.add_argument("csv_path")
    parser.add_argument("--verify", action="store_true", help="Run the LLM verify pass (requires Ollama).")
    parser.add_argument("--direction-check", action="store_true")
    parser.add_argument("--wellformedness-check", action="store_true")
    args = parser.parse_args()

    summary = run(args.csv_path, args.verify, args.direction_check, args.wellformedness_check)
    print(summary)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_run_verification_pipeline.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: all tests across every task pass (roughly 60 tests).

- [ ] **Step 6: Commit**

```bash
git add run_verification_pipeline.py tests/test_run_verification_pipeline.py
git commit -m "Add run_verification_pipeline.py wiring script"
```

---

### Task 13: Document how to run the real comparison later

**Files:**
- Modify: `README.md`

**Interfaces:** none (documentation only).

This project cannot reach the Docker-hosted Ollama instance from this session (see spec §10). This task leaves exact, copy-pasteable next steps for whoever runs the real comparison.

- [ ] **Step 1: Add a new README section**

Insert into `README.md`, after the existing "Testing prompt changes without touching Neo4j" section (after the `test_extraction_variants.py` subsection, before "## Known Issues"):

```markdown
## Comparing extraction/verification configurations (strict prompt, two-step verify)

Three configurations can now be compared on the same ground-truth pages, using the
harness in `eval/` and `prompts/` (see
`docs/superpowers/specs/2026-09-21-extraction-verification-design.md` for the full
design). None of this touches Neo4j.

1. Run each configuration against a page you have ground truth for (e.g. page 3) and
   save the output CSV:
   - **(A) Current live prompt** (unchanged): `python test_extraction.py papers/garo_1.pdf 3`
   - **(B) Strict tacit-only prompt**: swap `kg_extractor.make_extraction_prompt` for
     `prompts.loader.load_prompt("extraction_strict_tacit_v1")` in a small script
     following the same pattern as `test_extraction_variants.py`, then run it the same
     way.
   - **(C) Broad-v2 + verify**: same swap with `extraction_broad_v2`, then run
     `python run_verification_pipeline.py output/<the_csv_from_broad_v2> --verify --direction-check --wellformedness-check`.
2. Score each resulting CSV against the ground truth:
   ```bash
   python -m eval.run_eval output/<csv_from_A> --pages 3 --label "A: live prompt"
   python -m eval.run_eval output/<csv_from_B> --pages 3 --label "B: strict tacit-only"
   python -m eval.run_eval output/<csv_from_C>_refined.csv --pages 3 --label "C: broad-v2 + verify"
   ```
3. Compare the rows in `eval/results.csv` (git-tracked) for precision/recall/F1
   (strict + lenient), hallucination rate, and triples/page. Check
   `output/<...>_reviewed_out.csv`, `_direction_flags.csv`, and
   `_wellformedness_flags.csv` for anything worth a manual look.
4. `run_verification_pipeline.py --verify` requires Ollama reachable at
   `OLLAMA_VERIFY_URL` (defaults to `http://localhost:11434/api/generate`; inside the
   `app` container use `http://ollama:11434/api/generate`, same convention as
   `OLLAMA_URL` elsewhere in this project).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document how to run the extraction/verification comparison"
```

---

## Self-review notes

- **Spec coverage:** every numbered section of the spec (§4 prompts, §5 verify pass, §6.1 direction check, §6.2 well-formedness check, §7.1-7.4 ground truth + scorer + CLI + honest validation, §7.5 wiring script) has a corresponding task. §8 (future work) and §10 (execution plan) are explicitly out of scope for this plan's tasks — §10 is covered by Task 13's documentation, not by executing it.
- **No placeholders:** every code block is complete, runnable code; every prompt file is real, final text; every test asserts concrete values (all Jaccard/word-count/page-count numbers were computed and verified against real data while writing this plan, not assumed).
- **Type/signature consistency checked:** `Triple = tuple[str, str, str]` (Task 5) is used consistently in `eval/scorer.py` and `eval/run_eval.py` (Task 7); `JudgeFn` (Task 11) is imported and reused as the `judge_fn` parameter type in `run_verification_pipeline.py` (Task 12); `GroundTruthTriple.pages` (Task 4) is a `frozenset[str]` throughout, matched by `triples_for_pages`'s intersection check.
