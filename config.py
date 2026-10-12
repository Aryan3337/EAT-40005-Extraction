"""Neo4j connection configuration.

The graph stores sentence_ref -- verbatim text from the source papers -- on a
managed cloud instance, so the connection to a remote host must be encrypted.

This used to prepend neo4j+s:// only when the URI had no scheme at all, which
meant a .env containing `neo4j://<host>.databases.neo4j.io` connected in the
clear and nothing said so: TLS was a default, not a requirement. It is now
required for any host that is not on our own network. A local or self-hosted
Neo4j has no certificate and needs none, so those are still allowed
unencrypted -- the same shape as llm_endpoint.py's rule, and it keeps
self-hosting viable if external storage of source text is ever ruled out.
"""

import os
from urllib.parse import urlparse

from dotenv import load_dotenv

from llm_endpoint import is_private_host

load_dotenv()

ENCRYPTED_SCHEMES = {"neo4j+s", "neo4j+ssc", "bolt+s", "bolt+ssc"}
UNENCRYPTED_SCHEMES = {"neo4j", "bolt"}


class InsecureNeo4jURI(RuntimeError):
    """An unencrypted Neo4j connection to a remote host was configured."""


def resolve_neo4j_uri(raw):
    """Normalise NEO4J_URI, requiring TLS for anything off our own network.

    Returns None for an absent value rather than raising: config is imported
    by rag.py and the loader even when Neo4j is not in use, and
    Neo4jRAGSkeleton already raises a clearer error when it actually needs a
    URI.
    """
    uri = (raw or "").strip()
    if not uri:
        return None

    # What the Aura console hands you is a bare hostname.
    if "://" not in uri:
        return f"neo4j+s://{uri}"

    scheme = urlparse(uri).scheme.lower()
    if scheme in ENCRYPTED_SCHEMES:
        return uri

    if scheme in UNENCRYPTED_SCHEMES:
        host = urlparse(uri).hostname
        if is_private_host(host or ""):
            return uri
        raise InsecureNeo4jURI(
            f"Refusing an unencrypted Neo4j connection to a remote host: "
            f"{uri!r}.\n\n"
            f"The graph stores verbatim source-paper text (sentence_ref), so "
            f"this connection must be encrypted. Use neo4j+s:// instead of "
            f"{scheme}:// -- or just the bare hostname, which is upgraded "
            f"automatically.\n\n"
            f"Unencrypted is allowed only for a local or self-hosted "
            f"instance (localhost, a private address, or a container name)."
        )

    # Anything else is not a Neo4j URI we recognise; hand it to the driver
    # and let it produce its own error rather than guessing.
    return uri


URI = resolve_neo4j_uri(os.getenv("NEO4J_URI"))
USERNAME = os.getenv("NEO4J_USERNAME")
PASSWORD = os.getenv("NEO4J_PASSWORD")
