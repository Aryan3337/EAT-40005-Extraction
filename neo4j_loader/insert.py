from neo4j_loader.connection import get_driver
from neo4j_loader.cleaner import clean_relation

driver = get_driver()

def insert_triple(tx, triple):
    subject = triple["subject"]
    relation = clean_relation(triple.get("predicate", triple.get("relation", "RELATED_TO")))
    obj = triple["object"]

    query = f"""
    MERGE (s:Entity {{name: $subject}})
    MERGE (o:Entity {{name: $object}})
    MERGE (s)-[r:{relation}]->(o)
    SET r.source_file = $source_file,
        r.source_section = $source_section,
        r.confidence = $confidence,
        r.passage = $passage,
        r.sentence_ref = $sentence_ref
    """

    tx.run(
        query,
        subject=subject,
        object=obj,
        source_file=triple.get("source_file", ""),
        source_section=triple.get("source_section", ""),
        confidence=triple.get("confidence", ""),
        passage=triple.get("passage", ""),
        sentence_ref=triple.get("sentence_ref", "")
    )

def add_triples(triples):
    inserted = 0
    skipped = 0

    with driver.session() as session:
        for triple in triples:
            if triple["subject"] != "UNKNOWN":
                session.execute_write(insert_triple, triple)
                inserted += 1
            else:
                skipped += 1

    if inserted > 0:
        print(f"Uploaded {inserted} triples to Neo4j.")
    else:
        print("No triples uploaded to Neo4j — all candidates were UNKNOWN or invalid.")

    if skipped > 0:
        print(f"Skipped {skipped} UNKNOWN/invalid triples.")

    return inserted, skipped
