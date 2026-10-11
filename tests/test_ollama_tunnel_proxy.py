"""Tests for ollama_tunnel_proxy.py -- the auth gate in front of the
Tailscale Funnel tunnel to the team laptop's Ollama.

WHY THIS EXISTS: binding Ollama to a non-loopback address (needed so
Funnel's public traffic can reach it -- Ollama's own Host-header check only
runs when bound to loopback) removes Ollama's only built-in protection.
Without this proxy, anyone who found the public Funnel URL while it was on
could send it prompts and spend the laptop's compute, free, no password.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from ollama_tunnel_proxy import SECRET_HEADER, check_tunnel_secret, make_handler


# -- check_tunnel_secret -------------------------------------------------------


def test_the_right_secret_is_accepted():
    assert check_tunnel_secret("hunter2-long-random", expected="hunter2-long-random")


def test_a_wrong_secret_is_refused():
    assert not check_tunnel_secret("wrong", expected="hunter2-long-random")


def test_a_missing_secret_is_refused():
    assert not check_tunnel_secret(None, expected="hunter2-long-random")


def test_an_unconfigured_expected_secret_fails_closed():
    # No secret configured must refuse everything, never wave requests
    # through -- same discipline as admin_ingest.py's check_admin_secret.
    assert not check_tunnel_secret("anything", expected="")
    assert not check_tunnel_secret("anything", expected=None)


# -- the proxy end to end -------------------------------------------------------


class _FakeOllama(BaseHTTPRequestHandler):
    """Stands in for Ollama: records the Host header it received and the
    request body, then returns a canned response."""

    received_host = None
    received_body = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        _FakeOllama.received_body = self.rfile.read(length)
        _FakeOllama.received_host = self.headers.get("Host")
        body = json.dumps({"response": "a real answer"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # keep test output quiet


@pytest.fixture
def fake_ollama():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def proxy(fake_ollama):
    handler = make_handler(fake_ollama, "the-real-secret")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_a_request_with_the_right_secret_is_forwarded(proxy):
    response = requests.post(
        f"{proxy}/api/generate",
        json={"model": "mistral:7b", "prompt": "hello"},
        headers={SECRET_HEADER: "the-real-secret"},
        timeout=5,
    )
    assert response.status_code == 200
    assert response.json() == {"response": "a real answer"}


def test_a_request_with_the_wrong_secret_never_reaches_ollama(proxy):
    _FakeOllama.received_body = None
    response = requests.post(
        f"{proxy}/api/generate",
        json={"model": "mistral:7b", "prompt": "hello"},
        headers={SECRET_HEADER: "guessed-wrong"},
        timeout=5,
    )
    assert response.status_code == 403
    assert _FakeOllama.received_body is None


def test_a_request_with_no_secret_header_is_refused(proxy):
    response = requests.post(
        f"{proxy}/api/generate",
        json={"model": "mistral:7b", "prompt": "hello"},
        timeout=5,
    )
    assert response.status_code == 403


def test_the_forwarded_request_tells_ollama_it_is_local(proxy):
    # This is what actually satisfies Ollama's own Host-header check,
    # regardless of what Host header the real public request arrived with.
    requests.post(
        f"{proxy}/api/generate",
        json={"model": "mistral:7b", "prompt": "hello"},
        headers={SECRET_HEADER: "the-real-secret"},
        timeout=5,
    )
    assert _FakeOllama.received_host == "localhost"


def test_an_unreachable_upstream_returns_502_not_a_hang():
    # Point at a port nothing is listening on.
    handler = make_handler("http://127.0.0.1:1", "the-real-secret")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = requests.post(
            f"http://127.0.0.1:{server.server_port}/api/generate",
            json={"model": "mistral:7b", "prompt": "hello"},
            headers={SECRET_HEADER: "the-real-secret"},
            timeout=5,
        )
        assert response.status_code == 502
    finally:
        server.shutdown()
