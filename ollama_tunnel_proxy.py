#!/usr/bin/env python3
"""A tiny authenticating reverse proxy in front of Ollama, for the hosted
demo's Tailscale Funnel tunnel.

WHY THIS EXISTS: Ollama has a built-in check that rejects any request whose
Host header isn't localhost/a private address -- but that check ONLY runs
when Ollama itself is bound to a loopback address. Tailscale Funnel's public
traffic needs Ollama bound more widely to reach it at all, which silently
turns that one protection off. Once Funnel is on, the public URL would have
no password: anyone who found it could send it prompts and spend the
laptop's compute, for as long as the tunnel stays up.

This proxy restores a gate without needing Ollama exposed at all:
    - Ollama goes back to its safe loopback-only default (OLLAMA_HOST unset,
      or 127.0.0.1:11434).
    - This proxy listens on its own local port instead.
    - `tailscale funnel` points at THIS proxy's port, not Ollama's.
    - Only a request carrying the correct shared secret (OLLAMA_TUNNEL_SECRET,
      header X-Tunnel-Secret) is forwarded to Ollama; everything else gets a
      403 before it ever reaches the model.
    - The forwarded request's Host header is set to "localhost" explicitly,
      which keeps Ollama's own check happy regardless of what the original
      public request's Host header was.

Usage:
    OLLAMA_TUNNEL_SECRET=<a long random value> python ollama_tunnel_proxy.py
    OLLAMA_TUNNEL_SECRET=<value> python ollama_tunnel_proxy.py --port 11435 --upstream http://127.0.0.1:11434
"""

import argparse
import os
import secrets as secrets_module
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from llm_endpoint import OLLAMA_TUNNEL_SECRET_HEADER as SECRET_HEADER

DEFAULT_PORT = 11435
DEFAULT_UPSTREAM = "http://127.0.0.1:11434"


def check_tunnel_secret(provided: str | None, *, expected: str | None) -> bool:
    """Fails closed: no configured secret means refuse every request,
    the same discipline as admin_ingest.py's check_admin_secret.
    """
    if not expected or not provided:
        return False
    return secrets_module.compare_digest(provided, expected)


def make_handler(upstream_url: str, secret: str):
    class ProxyHandler(BaseHTTPRequestHandler):
        def _forbidden(self) -> None:
            body = b'{"error": "forbidden"}'
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bad_gateway(self, error: Exception) -> None:
            body = f'{{"error": "upstream unavailable: {error}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _forward(self, method: str) -> None:
            # Always drain the body first, even on a 403 -- responding and
            # closing before the client has finished sending it races the
            # client's own write and surfaces as a connection-reset error on
            # its side, not a clean 403.
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length) if length else None

            if not check_tunnel_secret(self.headers.get(SECRET_HEADER), expected=secret):
                self._forbidden()
                return

            try:
                response = requests.request(
                    method,
                    upstream_url.rstrip("/") + self.path,
                    data=payload,
                    headers={"Host": "localhost", "Content-Type": "application/json"},
                    timeout=120,
                )
            except requests.RequestException as error:
                self._bad_gateway(error)
                return

            self.send_response(response.status_code)
            self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        def do_GET(self) -> None:
            self._forward("GET")

        def do_POST(self) -> None:
            self._forward("POST")

        # Keeps routine request logs concise, same convention as rag.py.
        def log_message(self, format: str, *args) -> None:
            print(f"Ollama tunnel proxy: {format % args}")

    return ProxyHandler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)))
    parser.add_argument("--upstream", default=os.environ.get("OLLAMA_UPSTREAM_URL", DEFAULT_UPSTREAM))
    args = parser.parse_args()

    secret = os.environ.get("OLLAMA_TUNNEL_SECRET", "")
    if not secret:
        print("OLLAMA_TUNNEL_SECRET must be set -- refusing to start unauthenticated.", file=sys.stderr)
        return 1

    handler = make_handler(args.upstream, secret)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Ollama tunnel proxy listening on http://127.0.0.1:{args.port}, forwarding to {args.upstream}")
    print(f"Point `tailscale funnel {args.port}` at this port, not Ollama's.")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
