"""Read-only loader for the manual ground-truth workbook (KG_extraction_Marcus.xlsx).
Never writes to the workbook. See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §7.1."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

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
