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
