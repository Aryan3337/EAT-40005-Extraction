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
