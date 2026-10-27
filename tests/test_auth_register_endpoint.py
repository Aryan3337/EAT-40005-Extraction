"""Covers what /auth/register does with the username field it was handed.

The distinction this file exists to protect is between a username that was
NOT SENT and one that was sent BLANK. 373333c wired username support through
AuthStore, but _handle_auth coerces the field with

    username = str(payload.get("username", ""))

so an absent field arrives at register() as "", which _normalise_username
rejects with "Username must be 3-30 characters...". Every client that does
not know about usernames -- curl, a script, the registration examples in
deploy/nectar/README.md -- therefore got a 400 quoting rules for a value it
never offered. The Flutter app always sends the field, so the UI never
showed it.

A blank username is still a 400: the caller tried to set one and failed, and
silently creating an account without it would hide their mistake.
"""

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rag
from rag import create_query_handler


class _FakeAuthStore:
    """Records what register() was called with. No database."""

    calls: list = []

    def __init__(self, *args, **kwargs):
        pass

    def register(self, email, password, username=None):
        type(self).calls.append({"email": email, "username": username})
        if username is not None:
            # Mirror the real validator closely enough to prove the endpoint
            # still surfaces its rejection, without importing it.
            cleaned = username.strip()
            if len(cleaned) < 3 or len(cleaned) > 30:
                raise ValueError(
                    "Username must be 3-30 characters and use only letters, "
                    "numbers, dots, underscores, or hyphens."
                )
        return {"token": "t", "email": email, "role": "user"}


@pytest.fixture()
def register_request(monkeypatch):
    _FakeAuthStore.calls = []
    monkeypatch.setattr(rag, "AuthStore", _FakeAuthStore)
    handler_cls = create_query_handler(object(), object())

    def post(body):
        raw = json.dumps(body).encode("utf-8")
        handler = handler_cls.__new__(handler_cls)
        handler.path = "/auth/register"
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = io.BytesIO(raw)
        sent = {}
        handler._send_json = lambda status, payload: sent.update(
            status=status, payload=payload
        )
        handler.do_POST()
        return sent, _FakeAuthStore.calls

    return post


def test_register_without_a_username_field_creates_the_account(register_request):
    sent, calls = register_request(
        {"email": "person@example.com", "password": "a strong password"}
    )

    assert sent["status"] == 201, sent
    # None, not "" -- an absent field means "this client has no username to
    # give", which is not the same as an empty one.
    assert calls[-1]["username"] is None


def test_register_with_a_blank_username_is_still_rejected(register_request):
    sent, _ = register_request(
        {
            "email": "person@example.com",
            "password": "a strong password",
            "username": "   ",
        }
    )

    assert sent["status"] == 400
    assert "3-30 characters" in sent["payload"]["error"]


def test_register_passes_a_supplied_username_through(register_request):
    sent, calls = register_request(
        {
            "email": "person@example.com",
            "password": "a strong password",
            "username": "New.User",
        }
    )

    assert sent["status"] == 201, sent
    # Normalisation is AuthStore's job (tests/test_auth_username_login.py);
    # the endpoint's job is to hand the value over untouched.
    assert calls[-1]["username"] == "New.User"
