# Manual Neo4j fixes

Data corrections applied directly to the graph after loading from CSVs,
that a future reload should preserve or re-apply.

## 2025-10-29 -- POPULATION subject

- **Was:** `(Population_Census_2022) -[POPULATION]-> (1,650,159)`
- **Now:** `(GaroCommunity) -[POPULATION]-> (1,650,159)`
- **Why:** The triple's subject was the extraction source ("Population Census
  2022") rather than the entity the figure is about. Retrieval for
  "how many people live in the Garo" placed this triple at fused rank 24
  (out of SYNTHESIS_EVIDENCE_LIMIT=20) so the model never saw it. After
  rewiring the subject, fused rank became 3.
- **Cypher:** See fix_population_subject.py
- **Also affects:** extraction prompt should be updated to prevent
  date-as-subject (see prompts/CHANGELOG.md).
