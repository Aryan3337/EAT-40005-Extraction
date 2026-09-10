"""Thin wrapper around the Neo4j driver so the rest of the code just calls
`run_query(cypher, **params)` and gets back a list of dicts."""

from neo4j import GraphDatabase

from . import config


class Neo4jConnection:
    def __init__(self, uri=None, user=None, password=None, database=None):
        self._driver = GraphDatabase.driver(
            uri or config.NEO4J_URI,
            auth=(user or config.NEO4J_USER, password or config.NEO4J_PASSWORD),
        )
        self._database = database or config.NEO4J_DATABASE

    def close(self):
        self._driver.close()

    def run(self, cypher, **params):
        with self._driver.session(database=self._database) as session:
            result = session.run(cypher, **params)
            return [record.data() for record in result]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
