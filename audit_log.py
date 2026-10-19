"""Structured, append-only audit log (ADM-2 / ADM-3 / ADM-4).

One JSON object per line, written to AUDIT_LOG_PATH (default
audit/audit_events.jsonl). It answers "who did what, when, and did it
work" for logins, admin decisions and graph-changing runs.

Rules this module enforces:
  * append-only -- nothing here rewrites or deletes a line;
  * never records secrets: any detail key that looks like a password,
    token or secret is dropped;
  * logging must never break the action being logged -- a failure to write
    is printed and swallowed.

Event types in use: auth.login, auth.register, admin.paper_upload,
admin.paper_review, admin.feedback_review, admin.user_update,
admin.user_delete, graph.load, graph.prune, graph.triple_review,
system.error.
"""

from __future__ import annotations

import getpass
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.Lock()
_SECRET_WORDS = ("password", "token", "secret", "authorization")


def log_path() -> Path:
    return Path(os.getenv("AUDIT_LOG_PATH", "audit/audit_events.jsonl"))


def current_operator() -> str:
    """Who is running a command-line job: OPERATOR if set, else the OS user."""
    explicit = os.getenv("OPERATOR", "").strip()
    if explicit:
        return explicit
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def log_event(
    event_type: str,
    *,
    actor: str = "",
    outcome: str = "success",
    ip: str = "",
    **details: Any,
) -> None:
    entry: Dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "actor": actor,
        "outcome": outcome,
    }
    if ip:
        entry["ip"] = ip
    for key, value in details.items():
        if any(word in key.lower() for word in _SECRET_WORDS):
            continue
        entry[key] = value
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, default=str)
        with _LOCK, open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception as error:  # never let logging break the action
        print(f"Audit log write failed: {type(error).__name__}: {error}")


def read_events(
    *,
    limit: int = 200,
    event_type: Optional[str] = None,
    outcome: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Newest first. Unreadable lines are skipped, not fatal."""
    path = log_path()
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if event_type and not str(row.get("type", "")).startswith(event_type):
                continue
            if outcome and row.get("outcome") != outcome:
                continue
            rows.append(row)
    rows.reverse()
    return rows[: max(1, min(int(limit), 1000))]


def recent_errors(limit: int = 10) -> List[Dict[str, Any]]:
    """Failed or errored events, for the dashboard's recent-errors view."""
    failing = [
        row for row in read_events(limit=1000)
        if row.get("outcome") in {"failure", "error"}
    ]
    return failing[:limit]
