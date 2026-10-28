"""The state of an extraction run, written where the admin screen already looks.

main.py is a ~72-minute subprocess, so nothing it returns can reach the HTTP
response that started it. What the admin sees has to be a state on disk.

That state goes into the SAME append-only queue.jsonl the confidence
framework writes to, rather than a store of its own. Three reasons: it is
already the audit trail, admin_ingest.current_queue already collapses it to
one row per paper with later entries winning, and /admin/queue is already
polled by the Flutter admin page -- so an extraction state appears in the UI
with no new route and no new polling.
"""

import json
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from admin_ingest import read_queue, safe_pdf_name

EXTRACTING = "extracting"
EXTRACTED = "extracted"
FAILED = "extraction_failed"


def start(paper: str, *, uploads_dir) -> None:
    """Record that extraction has begun. Appended, never substituted."""
    _append(uploads_dir, {"paper": safe_pdf_name(paper), "decision": EXTRACTING})


def state_for(paper: str, *, uploads_dir) -> dict | None:
    """The paper's latest queue entry, whoever wrote it, or None.

    Deliberately not filtered to extraction entries: a re-upload supersedes
    an old extraction, exactly as current_queue treats it.
    """
    name = safe_pdf_name(paper)
    latest = None
    for entry in read_queue(uploads_dir):
        if entry.get("paper") == name:
            latest = entry
    return latest



def finish(paper: str, *, triples_loaded: int, uploads_dir) -> None:
    """Record a completed run. Zero triples is a result, not a failure --
    it means nothing survived the three gates, which is them working."""
    _append(uploads_dir, {
        "paper": safe_pdf_name(paper),
        "decision": EXTRACTED,
        "triples_loaded": int(triples_loaded),
    })


def fail(paper: str, *, error: str, uploads_dir) -> None:
    """Record a run that did not complete, with enough detail to act on."""
    _append(uploads_dir, {
        "paper": safe_pdf_name(paper),
        "decision": FAILED,
        "error": str(error),
    })



# A normal run is ~72 minutes. Three hours is generous enough that a slow
# paper is never reaped, and short enough that a wedged one clears the same
# working day.
STALE_AFTER_SECONDS = 3 * 60 * 60


def reap_stale(*, uploads_dir, max_age_seconds: int = STALE_AFTER_SECONDS) -> list[str]:
    """Fail any extraction that was still running when the API went down.

    Called at startup. Without it a container restart mid-run leaves the
    paper's latest state as "extracting" with no process behind it, and
    nothing will ever move it: the admin sees a job that never ends and the
    one-at-a-time lock would refuse every later paper.

    Returns the papers it reaped, so the caller can log them.
    """
    now = datetime.now(timezone.utc)
    latest: dict[str, dict] = {}
    for entry in read_queue(uploads_dir):
        paper = entry.get("paper")
        if paper:
            latest[paper] = entry

    reaped = []
    for paper, entry in latest.items():
        if entry.get("decision") != EXTRACTING:
            continue
        try:
            started = datetime.fromisoformat(entry.get("at", ""))
        except (TypeError, ValueError):
            continue  # undateable: leave it rather than guess
        if (now - started).total_seconds() < max_age_seconds:
            continue
        fail(paper,
             error="API restarted during extraction; the run did not finish.",
             uploads_dir=uploads_dir)
        reaped.append(paper)
    return reaped



# neo4j_loader.insert.add_triples prints this after a real upload. It is the
# only honest count available: main.py itself prints nothing on the success
# path, and the refined CSV holds every valid triple, not the gated subset
# that actually reached the graph.
_UPLOADED = re.compile(r"Uploaded\s+(\d+)\s+triples to Neo4j")

# Absent on purpose: --no-gates. The human gate is at paper admission, so the
# three deterministic gates are the only thing standing between a model's
# output and the production graph. See NECTAR_BACKLOG.md.
_COMMAND = [sys.executable, "main.py"]


def run_extraction(paper: str, *, pdf_path, uploads_dir, runner=subprocess.run) -> None:
    """Run main.py against one paper, recording the state around it.

    Synchronous and ~72 minutes; callers run it on a thread. `runner` is
    injected so the tests never start a real extraction.
    """
    start(paper, uploads_dir=uploads_dir)
    command = _COMMAND + [str(pdf_path)]
    try:
        result = runner(command, capture_output=True, text=True)
    except Exception as error:  # a failure to even launch is still a failure
        fail(paper, error=f"{type(error).__name__}: {error}",
             uploads_dir=uploads_dir)
        return

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    _write_log(uploads_dir, paper, stdout, stderr)
    if result.returncode != 0:
        detail = (stderr or stdout).strip() or f"exit code {result.returncode}"
        fail(paper, error=detail[-2000:], uploads_dir=uploads_dir)
        return

    match = _UPLOADED.search(stdout + stderr)
    finish(paper, triples_loaded=int(match.group(1)) if match else 0,
           uploads_dir=uploads_dir)



# One extraction at a time. Two 72-minute runs against one CPU-only Ollama
# would make both crawl AND starve the chatbot that shares it, so a second
# caller is refused outright rather than queued -- there is one admin, and
# an honest "no" beats an invisible backlog that a restart would lose.
_RUNNING = threading.Lock()


def begin(paper: str, *, pdf_path, uploads_dir,
          runner=subprocess.run, spawn=None) -> bool:
    """Start an extraction in the background. False if one is already running.

    `spawn` is injected by the tests so a job runs inline; in production it
    is a daemon thread, the same shape _handle_admin_upload already uses for
    confidence scoring.
    """
    if not _RUNNING.acquire(blocking=False):
        return False

    def work():
        try:
            run_extraction(paper, pdf_path=pdf_path, uploads_dir=uploads_dir,
                           runner=runner)
        finally:
            # Without this a crash wedges every later paper until a restart.
            _RUNNING.release()

    if spawn is None:
        threading.Thread(target=work, daemon=True).start()
    else:
        spawn(work)
    return True


def is_running() -> bool:
    """True while an extraction holds the slot."""
    return _RUNNING.locked()


def _write_log(uploads_dir, paper: str, stdout: str, stderr: str) -> None:
    """Keep the run's output. It is the only diagnostic for a 72-minute job."""
    log_dir = Path(uploads_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    body = stdout
    if stderr:
        body += "\n--- stderr ---\n" + stderr
    (log_dir / f"{safe_pdf_name(paper)}.log").write_text(body, encoding="utf-8")


def _append(uploads_dir, entry: dict) -> None:
    directory = Path(uploads_dir)
    directory.mkdir(parents=True, exist_ok=True)
    entry = dict(entry)
    entry["at"] = datetime.now(timezone.utc).isoformat()
    entry["by"] = "extraction"
    with open(directory / "queue.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
