"""Both production drivers must verify a pooled connection before using it.

KNOWN_LIMITATIONS 31. The neo4j 6.4.1 defaults are
`liveness_check_timeout = None` (never check) and
`max_connection_lifetime = 3600`, so after any idle gap long enough for
AuraDB or the NAT to reap the TCP connection, the pool hands out a dead
socket. Every production call site uses unmanaged `session.run()`, which the
driver does not retry, so the resulting `SessionExpired` /
`ServiceUnavailable` surfaced as HTTP 503 on sign-in and 502 on a query.

These tests pin the pool setting on both drivers. They assert on the keyword
arguments the driver is constructed with, because that is the whole fix --
there is no behaviour to observe without an idle AuraDB connection to kill.
"""

import unittest
from unittest.mock import MagicMock, patch

import auth_store as auth_store_module
import config as config_module
import rag


class _CapturingDriver:
    """Enough of a driver for a constructor to run against."""

    def __init__(self):
        self.kwargs = {}

    def __call__(self, *args, **kwargs):
        self.kwargs = kwargs
        return MagicMock()


class PoolConfigTests(unittest.TestCase):
    def test_auth_store_driver_checks_liveness(self):
        capture = _CapturingDriver()
        with patch.multiple(
            auth_store_module, URI="neo4j://localhost", USERNAME="u", PASSWORD="p"
        ):
            with patch.object(
                auth_store_module.GraphDatabase, "driver", new=capture
            ):
                auth_store_module.AuthStore()

        self.assertIn("liveness_check_timeout", capture.kwargs)
        self.assertIsNotNone(capture.kwargs["liveness_check_timeout"])
        self.assertGreater(capture.kwargs["liveness_check_timeout"], 0)

    def test_retrieval_driver_checks_liveness(self):
        capture = _CapturingDriver()
        with patch.multiple(
            config_module, URI="neo4j://localhost", USERNAME="u", PASSWORD="p"
        ):
            with patch.object(rag.GraphDatabase, "driver", new=capture):
                rag.Neo4jRAGSkeleton()

        self.assertIn("liveness_check_timeout", capture.kwargs)
        self.assertIsNotNone(capture.kwargs["liveness_check_timeout"])
        self.assertGreater(capture.kwargs["liveness_check_timeout"], 0)

    def test_both_drivers_agree_on_the_timeout(self):
        # One number, so the two drivers cannot drift the way the two
        # refusal tables did (see tests/test_no_evidence_message.py).
        auth_capture = _CapturingDriver()
        rag_capture = _CapturingDriver()
        with patch.multiple(
            auth_store_module, URI="neo4j://localhost", USERNAME="u", PASSWORD="p"
        ):
            with patch.object(
                auth_store_module.GraphDatabase, "driver", new=auth_capture
            ):
                auth_store_module.AuthStore()
        with patch.multiple(
            config_module, URI="neo4j://localhost", USERNAME="u", PASSWORD="p"
        ):
            with patch.object(rag.GraphDatabase, "driver", new=rag_capture):
                rag.Neo4jRAGSkeleton()

        self.assertEqual(
            auth_capture.kwargs["liveness_check_timeout"],
            rag_capture.kwargs["liveness_check_timeout"],
        )


if __name__ == "__main__":
    unittest.main()
