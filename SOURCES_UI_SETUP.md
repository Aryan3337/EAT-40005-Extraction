# Sources UI — SCRUM-354 / SCRUM-355

This patch preserves provenance through CSV retrieval, Neo4j storage/retrieval,
Flutter source cards, and saved chat history. It does not alter answer generation
or invent source metadata.

## Recorded fields

- `paper_title`: the verified publication title (not a guessed filename expansion).
- `source_file`: the recorded filename, shown separately from title.
- `page_number`: positive PDF page index; explicit value wins, otherwise only
  a complete `Page N` source_section can supply the index. A PDF page index
  may differ from a publication's printed page label.
- `source_type`: explicitly `research_paper` or `community_data`.

Missing titles/pages/types are visibly marked unavailable/unknown. Existing
section, quote, triple and confidence remain visible. Labels support en/hi/bn.
Old saved conversations without these fields continue to load.

## Important data limitation

The tracked production CSVs have source filenames and PDF pages but lack verified
paper titles and source types. The demo data.csv has even less provenance.
The patch cannot manufacture those details. An authorized curator must supply
verified metadata on the corresponding records. Do not classify all existing
records as research papers or infer community data from missing filenames.

CSV mode: include the four fields above in the input CSV passed with --kg.
Neo4j mode: existing relationships need a separately reviewed metadata backfill
or reload from verified enriched CSVs. This patch does not modify your database.
The loader stores the new fields on future loads. Review existing load/MERGE
behavior before reloading; a relationship still represents only one provenance
record and repeat facts from multiple papers can overwrite earlier provenance.
This patch does not redesign that schema.

## Validate on Mac

From repository root:

    .venv/bin/python -m unittest discover -s tests -p test_source_provenance.py -v
    .venv/bin/python -m pytest tests/test_insert.py -q

From flutter_application:

    dart format lib/models/chat_message.dart lib/features/chat/chat_page.dart lib/app/app_localizations.dart test/source_provenance_test.dart
    flutter analyze
    flutter test

Inspect source cards for a research record, a community record, and a legacy
record with absent metadata. Also check sources after saving/reopening history
and after switching English/Hindi/Bangla. Keep screenshots for the Jira tasks.

Validation in the preparation environment: six Python normalization tests passed,
Python compilation and git diff --check passed. Flutter/Dart and pytest were not
available there; run the commands above before committing.
