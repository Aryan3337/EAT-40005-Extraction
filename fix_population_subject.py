"""Rewire the POPULATION triple: subject Population_Census_2022 -> GaroCommunity.

Trial-instance-only. Run with no args:
    python fix_population_subject.py

Verifies the subject/object/sentence_ref before and after, so you can see
exactly what changed.
"""
from dotenv import load_dotenv
load_dotenv()

from neo4j import GraphDatabase
from config import URI, USERNAME, PASSWORD

CHECK_CYPHER = """
MATCH (a:Entity)-[r:POPULATION]->(b:Entity)
RETURN a.name AS subject, b.name AS object,
       coalesce(r.sentence_ref, '') AS sentence_ref
"""

REWIRE_CYPHER = """
MATCH (p:Entity {name: 'Population_Census_2022'})-[rel:POPULATION]->(v)
MATCH (g:Entity {name: 'GaroCommunity'})
CREATE (g)-[nr:POPULATION]->(v)
SET nr = properties(rel)
DELETE rel
RETURN g.name AS new_subject, v.name AS object, nr.sentence_ref AS sentence_ref
"""

driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))
with driver.session() as s:
    print("=== BEFORE ===")
    before = list(s.run(CHECK_CYPHER))
    if not before:
        print("  No POPULATION triples found. Nothing to rewire.")
        driver.close()
        raise SystemExit
    for row in before:
        print(f"  ({row['subject']}) -[POPULATION]-> ({row['object']})")
        print(f"    sentence_ref: {row['sentence_ref'][:120]!r}")

    print("\n=== REWIRING ===")
    result = s.run(REWIRE_CYPHER).single()
    if result is None:
        print("  Rewire matched nothing. Expected a node named "
              "'Population_Census_2022' with a POPULATION relationship. "
              "The subject may already be fixed, or the name differs.")
    else:
        print(f"  New triple: ({result['new_subject']}) -[POPULATION]-> ({result['object']})")
        print(f"  sentence_ref preserved: {result['sentence_ref'][:120]!r}")

    print("\n=== AFTER ===")
    after = list(s.run(CHECK_CYPHER))
    for row in after:
        print(f"  ({row['subject']}) -[POPULATION]-> ({row['object']})")

driver.close()
print("\nDone.")