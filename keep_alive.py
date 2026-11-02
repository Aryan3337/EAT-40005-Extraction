#!/usr/bin/env python3
"""
keep_alive.py -- send a trivial query to the Neo4j instance so Aura Free
does not pause it for inactivity (it pauses after ~3 days without queries).

Reads NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD from the environment or
from .env (same variables as config.py). Standalone on purpose: it does not
import config.py, so it works on any branch.

USAGE
    python keep_alive.py                 # ping once and exit (use with a scheduler)
    python keep_alive.py --loop          # ping now, then every 2.5 days, forever
    python keep_alive.py --loop --hours 48
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from neo4j import GraphDatabase

QUERY = "RETURN 1 AS ok"          # read-only; touches no data
DEFAULT_INTERVAL_HOURS = 60       # 2.5 days


def connect_uri(raw):
    uri = (raw or "").strip()
    if not uri:
        sys.exit("NEO4J_URI is not set (put it in .env or the environment).")
    return uri if "://" in uri else f"neo4j+s://{uri}"   # Aura gives a bare host


def ping():
    load_dotenv()
    user, pw = os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")
    if not user or not pw:
        sys.exit("NEO4J_USERNAME / NEO4J_PASSWORD are not set.")
    with GraphDatabase.driver(connect_uri(os.getenv("NEO4J_URI")), auth=(user, pw)) as driver:
        driver.verify_connectivity()
        record = driver.execute_query(QUERY).records[0]
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{stamp}] keep-alive OK (RETURN 1 -> {record['ok']})", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--loop", action="store_true", help="keep running and ping on an interval")
    ap.add_argument("--hours", type=float, default=DEFAULT_INTERVAL_HOURS,
                    help="hours between pings with --loop (default 60 = 2.5 days)")
    args = ap.parse_args()
    if not args.loop:
        ping()
        return
    while True:
        try:
            ping()
        except SystemExit:
            raise
        except Exception as exc:          # a failed ping must not kill the loop
            print(f"keep-alive FAILED: {exc!r} -- retrying in 1 hour", file=sys.stderr, flush=True)
            time.sleep(3600)
            continue
        time.sleep(args.hours * 3600)


if __name__ == "__main__":
    main()
