"""Tests for config.py's Neo4j URI handling.

WHY: the graph stores sentence_ref, which is verbatim text from the source
papers, on a managed cloud instance. That connection has to be encrypted.

config.py only prepended neo4j+s:// when the URI had NO scheme, so a .env
containing neo4j://cf02815e.databases.neo4j.io connected unencrypted and
nothing said so. TLS was the default rather than a requirement.

A local or self-hosted Neo4j legitimately runs without TLS, so the rule is
the same shape as llm_endpoint.py's: encryption is required for hosts that
are not ours.
"""

import pytest

from config import InsecureNeo4jURI, resolve_neo4j_uri


# -- the bare-hostname case AuraDB actually gives you -------------------------


def test_a_bare_aura_hostname_is_upgraded_to_an_encrypted_scheme():
    # This is what the Aura console hands you, and what the committed .env
    # on main contained.
    assert resolve_neo4j_uri("cf02815e.databases.neo4j.io") == \
        "neo4j+s://cf02815e.databases.neo4j.io"


# -- schemes that are already encrypted --------------------------------------


@pytest.mark.parametrize("uri", [
    "neo4j+s://cf02815e.databases.neo4j.io",
    "neo4j+ssc://cf02815e.databases.neo4j.io",
    "bolt+s://cf02815e.databases.neo4j.io",
    "bolt+ssc://cf02815e.databases.neo4j.io",
])
def test_an_already_encrypted_uri_is_left_alone(uri):
    assert resolve_neo4j_uri(uri) == uri


# -- the hole this closes -----------------------------------------------------


@pytest.mark.parametrize("uri", [
    "neo4j://cf02815e.databases.neo4j.io",
    "bolt://cf02815e.databases.neo4j.io",
    "neo4j://some-host.example.com:7687",
])
def test_an_unencrypted_scheme_to_a_remote_host_is_refused(uri):
    # Previously honoured verbatim: "://" was present, so no upgrade, and
    # the driver connected in the clear.
    with pytest.raises(InsecureNeo4jURI):
        resolve_neo4j_uri(uri)


def test_the_refusal_names_the_scheme_to_use():
    with pytest.raises(InsecureNeo4jURI) as excinfo:
        resolve_neo4j_uri("neo4j://cf02815e.databases.neo4j.io")
    assert "neo4j+s://" in str(excinfo.value)


# -- local and self-hosted Neo4j ---------------------------------------------


@pytest.mark.parametrize("uri", [
    "bolt://localhost:7687",
    "neo4j://localhost:7687",
    "bolt://127.0.0.1:7687",
    "neo4j://neo4j:7687",            # a docker-compose service name
    "bolt://192.168.1.20:7687",
])
def test_an_unencrypted_connection_to_our_own_network_is_allowed(uri):
    # A local or self-hosted instance has no certificate and needs none;
    # requiring TLS here would just block the self-hosting option.
    assert resolve_neo4j_uri(uri) == uri


# -- absent configuration -----------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_an_empty_uri_stays_empty_rather_than_becoming_a_scheme(raw):
    # config.py is imported by rag.py and the loader even when Neo4j is not
    # in use, so a missing NEO4J_URI must not raise at import time --
    # Neo4jRAGSkeleton raises its own clearer error when it needs one.
    assert resolve_neo4j_uri(raw) is None
