#!/usr/bin/env python3
"""End-to-end smoke check: is the system actually working right now?

The 177 unit tests all run in-process. Not one of them crosses a boundary --
nothing exercises add_triples against a real database, the HTTP API, or
extraction into storage. This script covers those seams, and it is the
command to hand to whoever inherits the project as "how do I know it still
works".

    python smoke_test.py                      # Neo4j stages only
    python smoke_test.py --api http://127.0.0.1:8000
    python smoke_test.py --api https://<hosted-api>

Each stage reports PASS, FAIL or SKIP. A SKIP means the infrastructure for
that stage is not up yet and says what is missing; it is not a pass. The
exit code is non-zero only on FAIL, so this is safe to run before the
database exists.
"""

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
_results: list[tuple[str, str, str]] = []


def record(stage: str, status: str, detail: str = "") -> str:
    _results.append((stage, status, detail))
    symbol = {PASS: "[PASS]", FAIL: "[FAIL]", SKIP: "[SKIP]"}[status]
    print(f"{symbol} {stage}")
    if detail:
        for line in detail.splitlines():
            print(f"         {line}")
    return status


# -- stage 1: the gated corpus on disk ---------------------------------------


def check_refined_csvs(papers: list[str]) -> list[dict]:
    rows: list[dict] = []
    missing = []
    for paper in papers:
        # output/ is gitignored; data/production_graph/ is the tracked copy.
        name = f"{paper}_kg_refined.csv"
        path = next((d / name for d in (Path("output"), Path("data") / "production_graph")
                     if (d / name).exists()), None)
        if path is None:
            missing.append(name)
            continue
        with open(path, newline="", encoding="utf-8") as f:
            rows += list(csv.DictReader(f))

    if missing:
        record("Gated corpus on disk", FAIL,
               "missing: " + ", ".join(missing) +
               "\nRun: python run_verification_pipeline.py ... --quote-check --pdf ...")
        return []

    cited = sum(1 for r in rows if (r.get("sentence_ref") or "").strip())
    record("Gated corpus on disk", PASS,
           f"{len(rows)} triples across {len(papers)} papers; "
           f"{cited} carry a sentence_ref")
    return rows


# -- stage 2: configuration ---------------------------------------------------


def check_config():
    try:
        import config
    except Exception as error:
        record("Neo4j configuration", FAIL, str(error))
        return None

    if not (config.URI and config.USERNAME and config.PASSWORD):
        record("Neo4j configuration", SKIP,
               "NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD not all set in .env.\n"
               "The AuraDB instance probably does not exist yet. See .env.example.")
        return None

    encrypted = config.URI.startswith(("neo4j+s://", "neo4j+ssc://",
                                       "bolt+s://", "bolt+ssc://"))
    host = config.URI.split("://")[-1]
    if not encrypted:
        record("Neo4j configuration", PASS,
               f"{config.URI} (unencrypted -- expected only for a local instance)")
    else:
        record("Neo4j configuration", PASS, f"encrypted connection to {host}")
    return config


# -- stage 3: the graph itself -----------------------------------------------


def check_graph(config_module, expected_triples: list[dict]):
    try:
        from neo4j_loader.connection import get_driver
        driver = get_driver()
    except Exception as error:
        record("Neo4j reachable", FAIL, f"{type(error).__name__}: {error}")
        return None

    try:
        with driver.session() as session:
            rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            runs = [r["run_id"] for r in session.run(
                "MATCH ()-[r]->() WHERE r.run_id IS NOT NULL "
                "RETURN DISTINCT r.run_id AS run_id ORDER BY run_id")]
    except Exception as error:
        record("Neo4j reachable", FAIL,
               f"{type(error).__name__}: {error}\n"
               f"A DNS failure here usually means the AuraDB instance was "
               f"deleted or paused -- free-tier instances pause after 3 idle "
               f"days and are deleted after 30.")
        return None

    record("Neo4j reachable", PASS, f"{nodes} nodes, {rels} relationships")

    # Run identity: the whole point of run_id is that a load is findable.
    if not runs:
        record("Run identity present", FAIL,
               "No relationship carries a run_id. Either the graph was loaded "
               "before run identity existed, or the load bypassed add_triples. "
               "Reload with: python load_production_graph.py")
    else:
        record("Run identity present", PASS,
               f"{len(runs)} load(s) distinguishable; most recent {runs[-1]}")

    # Provenance: every fact the chatbot shows must carry its citation.
    try:
        with driver.session() as session:
            uncited = session.run(
                "MATCH ()-[r]->() WHERE r.sentence_ref IS NULL OR r.sentence_ref = '' "
                "RETURN count(r) AS c").single()["c"]
    except Exception as error:
        uncited = None
        record("Every fact carries a citation", FAIL, str(error))

    if uncited == 0:
        record("Every fact carries a citation", PASS, "no uncited relationships")
    elif uncited:
        record("Every fact carries a citation", FAIL,
               f"{uncited} relationships have no sentence_ref -- the chatbot "
               f"would show a fact with nothing behind it")

    # A triple we know should be there, found by name rather than by id.
    if expected_triples:
        sample = expected_triples[0]
        try:
            with driver.session() as session:
                found = session.run(
                    "MATCH (s:Entity {name: $s})-[r]->(o:Entity {name: $o}) "
                    "RETURN type(r) AS predicate, r.sentence_ref AS ref, "
                    "r.source_section AS page LIMIT 1",
                    s=sample["subject"], o=sample["object"]).single()
        except Exception as error:
            found = None
            record("A known triple round-trips", FAIL, str(error))

        label = f"({sample['subject']})-[{sample['predicate']}]->({sample['object']})"
        if found is None:
            record("A known triple round-trips", FAIL,
                   f"{label} is in the gated CSV but not in the graph. "
                   f"The load did not run, or ran against a different instance.")
        elif not (found["ref"] or "").strip():
            record("A known triple round-trips", FAIL,
                   f"{label} is present but carries no sentence_ref")
        else:
            record("A known triple round-trips", PASS,
                   f"{label}\npage {found['page'] or '?'}, cited")

    return driver


# -- stage 4: the HTTP API ----------------------------------------------------


def check_api(api_base: str, expected_triples: list[dict]):
    if not api_base:
        record("Chatbot API answers", SKIP,
               "No --api given. Start it with:\n"
               "    python rag.py --serve --neo4j\n"
               "then re-run with --api http://127.0.0.1:8000")
        return

    health = api_base.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(health, timeout=10) as response:
            json.load(response)
    except Exception as error:
        record("API health", FAIL, f"{health}: {type(error).__name__}: {error}")
        return
    record("API health", PASS, health)

    # Ask about something the graph genuinely contains, taken from the corpus
    # rather than hardcoded -- a question the KG cannot answer would make this
    # fail for the wrong reason.
    if not expected_triples:
        record("Chatbot API answers", SKIP, "no gated corpus to build a question from")
        return

    subject = expected_triples[0]["subject"]
    question = f"Tell me about {subject}"
    payload = json.dumps({"query": question}).encode()
    request = urllib.request.Request(
        api_base.rstrip("/") + "/query", data=payload,
        headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.load(response)
    except Exception as error:
        record("Chatbot API answers", FAIL, f"{type(error).__name__}: {error}")
        return

    answer = (body.get("answer") or "").strip()
    triples = body.get("triples") or []

    if not answer:
        record("Chatbot API answers", FAIL, f"{question!r} returned an empty answer")
    else:
        record("Chatbot API answers", PASS,
               f"{question!r}\n-> {answer[:160]}{'...' if len(answer) > 160 else ''}")

    if not triples:
        record("Answer carries its evidence", FAIL,
               "the response has no 'triples', so the Flutter app would show "
               "an answer with no expandable sources")
        return

    with_page = [t for t in triples if (t.get("source_section") or "").strip()]
    if not with_page:
        record("Answer carries its evidence", FAIL,
               f"{len(triples)} triples returned, none with a source_section -- "
               f"the UI shows a page reference per fact")
    else:
        record("Answer carries its evidence", PASS,
               f"{len(triples)} triples, {len(with_page)} with a page reference")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", help="Base URL of a running rag.py API.")
    parser.add_argument("--papers", nargs="*", default=["garo_1", "garo_2", "garo_3"])
    args = parser.parse_args()

    print("EAT-40005 end-to-end smoke check\n")

    rows = check_refined_csvs(args.papers)
    config_module = check_config()
    if config_module is not None:
        check_graph(config_module, rows)
    else:
        record("Neo4j reachable", SKIP, "no configuration")
    check_api(args.api, rows)

    failed = [s for s, status, _ in _results if status == FAIL]
    skipped = [s for s, status, _ in _results if status == SKIP]
    print(f"\n{len(_results) - len(failed) - len(skipped)} passed, "
          f"{len(failed)} failed, {len(skipped)} skipped")
    if skipped:
        print("Skipped stages are NOT passes -- the infrastructure is not up yet:")
        for stage in skipped:
            print(f"  - {stage}")
    if failed:
        print("FAILED:")
        for stage in failed:
            print(f"  - {stage}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
