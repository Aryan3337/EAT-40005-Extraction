import os
from dotenv import load_dotenv

load_dotenv()

URI = os.getenv("NEO4J_URI")
USERNAME = os.getenv("NEO4J_USERNAME")
PASSWORD = os.getenv("NEO4J_PASSWORD")

# Accept a bare Neo4j hostname while keeping the secure AuraDB protocol.
if URI and "://" not in URI:
	URI = f"neo4j+s://{URI}"
