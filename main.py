import json

from neo4j_loader.insert import add_triples

with open("llm_output.json", "r") as file:

    triples = json.load(file)

add_triples(triples)