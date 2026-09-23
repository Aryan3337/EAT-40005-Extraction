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
