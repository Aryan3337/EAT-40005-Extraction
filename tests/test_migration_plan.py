"""ADM-5: the migration script is read-only unless explicitly approved."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("plan", ROOT / "scripts" / "plan_node_migration.py")
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class Conn:
    def __init__(self):
        self.queries = []

    def run(self, q, **p):
        self.queries.append(q)
        return [{"entities": 4, "updated": 3}]


def test_report_query_never_writes():
    c = Conn()
    plan.report(c)
    assert not any(w in c.queries[0] for w in ("SET ", "DELETE", "REMOVE", "CREATE", "MERGE"))


def test_backfill_is_additive_only():
    assert "DELETE" not in plan.BACKFILL and "REMOVE" not in plan.BACKFILL
    assert "SET n.sources" in plan.BACKFILL


def test_execute_requires_approver(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["plan", "--execute"])
    with pytest.raises(SystemExit):
        plan.main()


def test_script_runs_from_its_own_folder_without_import_errors():
    """Regression: `python scripts/plan_node_migration.py` once died with
    ModuleNotFoundError: pruner because only scripts/ was on the path."""
    import os
    import subprocess

    env = dict(os.environ, NEO4J_URI="bolt://127.0.0.1:1",
               NEO4J_USERNAME="u", NEO4J_PASSWORD="p")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "plan_node_migration.py")],
        cwd=ROOT / "scripts", env=env, capture_output=True, text=True, timeout=60,
    )
    assert "ModuleNotFoundError" not in result.stderr
