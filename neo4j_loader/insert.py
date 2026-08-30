from neo4j_loader.connection import get_driver
from neo4j_loader.cleaner import clean_relation

driver = get_driver()

def insert_triple(tx, subject, relation, obj):

    relation = clean_relation(relation)

    query = f"""
    MERGE (s:Entity {{name: $subject}})
    MERGE (o:Entity {{name: $object}})
    MERGE (s)-[:{relation}]->(o)
    """

    tx.run(
        query,
        subject=subject,
        object=obj
    )

def add_triples(triples):

    with driver.session() as session:

        for triple in triples:

            session.execute_write(
                insert_triple,
                triple["subject"],
                triple["relation"],
                triple["object"]
            )

    print("All triples inserted.")