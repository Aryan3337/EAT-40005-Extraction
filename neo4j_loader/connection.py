from neo4j import GraphDatabase
from config import URI, USERNAME, PASSWORD

driver = GraphDatabase.driver(
    URI,
    auth=(USERNAME, PASSWORD)
)

def get_driver():
    return driver