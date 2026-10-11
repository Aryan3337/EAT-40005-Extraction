# The production knowledge graph corpus

The 45 gated triples loaded into Neo4j, one CSV per paper. This is the
post-gate output of `main.py` — well-formedness, grounding and
quote-genuineness already applied.

| File | Triples |
|---|---|
| `garo_1_kg_refined.csv` | 16 |
| `garo_2_kg_refined.csv` | 24 |
| `garo_3_kg_refined.csv` | 5 |

## Why these are tracked when `output/` is gitignored

`.gitignore` excludes `output/`, so until now the entire extraction corpus
existed only on one laptop. That made two things impossible:

- **Deployment.** `rag.py` can serve without a database by reading a refined
  CSV (`--kg`), which is the rehearsed fallback for the demo. A hosted
  container has no `output/` directory.
- **Handover and reproducibility.** A fresh clone could not load the graph,
  and regenerating these from the PDFs costs about 3.4 hours of local LLM
  time at the measured 157 s/chunk.

Committed extraction CSVs are already established practice in this repo —
`DeepSeek Output/paper1_kg.csv` and `paper1_kg_extractions.csv` are tracked
on `main`.

## Note on contents

The `sentence_ref` and `passage` columns contain verbatim sentences from the
source papers. The same text is already stored in Neo4j AuraDB with the
supervisor's knowledge — she proposed AuraDB — so this does not introduce a
new category of exposure. It does mean paper excerpts are in git history,
which is worth being deliberate about rather than incidental.

If that is unwanted, `git rm -r --cached data/production_graph` and keep
these local; the cost is that deployment and a clean clone both need the
files supplied another way.

## The pre-gate corpus is NOT here

`output/garo_*_kg.csv` holds all 578 extracted candidates and is still local
only. That is the irreplaceable artefact — it is what the gates were tuned
against and what every number in `KNOWN_LIMITATIONS.md` was measured from.
It is not needed for deployment, so the decision to commit it is left open,
but it should be backed up somewhere.

## Regenerating these

```bash
# From a pre-gate extraction CSV, no LLM, about a second:
python run_verification_pipeline.py output/garo_1_kg.csv \
    --wellformedness-check --grounding-check --quote-check --pdf papers/garo_1.pdf

# Or the full path from the PDF, about 1.2 hours per paper:
python main.py papers/garo_1.pdf --dry-run
```

Note that `run_verification_pipeline.py` preserves only the input CSV's own
columns, so its output lacks `source_file` and `page_number`. The loader
needs `source_file`; these files came through `main.py`, which adds both.
