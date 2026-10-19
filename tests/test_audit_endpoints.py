"""ADM-1/2/3 end to end over a real local HTTP server with a fake auth store."""

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rag


class FakeStore:
    def login(self, email, password):
        if password == "right":
            return {"email": email, "role": "admin", "token": "tok"}
        return None

    def register(self, email, password):
        return {"email": email, "role": "user", "token": "t2"}

    def session(self, token):
        return {"email": "admin@x.com", "role": "admin"} if token == "tok" else (
            {"email": "u@x.com", "role": "user"} if token == "utok" else None)


class FakeSkeleton:
    def query(self, q):
        return []

    def graph_overview(self):
        return {"nodes": 5, "relationships": 7, "archived": 1,
                "sources": [{"source": "p.pdf", "triples": 7}]}


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(rag, "AuthStore", FakeStore)
    monkeypatch.setattr(rag, "UPLOADS_DIR", tmp_path / "uploads")
    handler = rag.create_query_handler(FakeSkeleton(), object())
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def call(base, path, body=None, token=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_logins_are_logged_without_password(server):
    assert call(server, "/auth/login", {"email": "a@x.com", "password": "wrong"})[0] == 401
    assert call(server, "/auth/login", {"email": "a@x.com", "password": "right"})[0] == 200
    status, body = call(server, "/admin/audit", token="tok")
    assert status == 200
    kinds = [(e["type"], e["outcome"]) for e in body["events"]]
    assert ("auth.login", "failure") in kinds and ("auth.login", "success") in kinds
    assert "wrong" not in json.dumps(body) and "right" not in json.dumps(body)


def test_audit_and_overview_need_an_admin(server):
    assert call(server, "/admin/audit")[0] == 401
    assert call(server, "/admin/audit", token="utok")[0] == 403
    assert call(server, "/admin/overview", token="utok")[0] == 403


def test_overview_reports_graph_papers_and_recent_errors(server):
    call(server, "/auth/login", {"email": "a@x.com", "password": "wrong"})
    status, body = call(server, "/admin/overview", token="tok")
    assert status == 200
    assert body["graph"]["nodes"] == 5 and body["graph"]["sources"][0]["source"] == "p.pdf"
    assert body["recent_errors"][0]["type"] == "auth.login"


def test_audit_filters_and_bad_limit(server):
    call(server, "/auth/login", {"email": "a@x.com", "password": "right"})
    status, body = call(server, "/admin/audit?type=auth&outcome=success", token="tok")
    assert status == 200 and len(body["events"]) == 1
    assert call(server, "/admin/audit?limit=abc", token="tok")[0] == 400
