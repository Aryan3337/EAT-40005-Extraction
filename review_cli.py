#!/usr/bin/env python3
"""
Minimal backend for the human-verification step: list what's been
flagged for review, and approve/reject items one at a time. This is a
stand-in for a proper review UI -- the underlying pruner.review functions
are what a Streamlit/Flask page would call instead.

Usage:
    python review_cli.py list
    python review_cli.py approve <element_id> --kind node
    python review_cli.py reject <element_id> --kind relationship
"""

import argparse
import json

from pruner.db import Neo4jConnection
from pruner import review


def main():
    parser = argparse.ArgumentParser(description="Review queue for flagged triples.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")

    approve_p = sub.add_parser("approve")
    approve_p.add_argument("element_id")
    approve_p.add_argument("--kind", choices=["node", "relationship"], default="node")

    reject_p = sub.add_parser("reject")
    reject_p.add_argument("element_id")
    reject_p.add_argument("--kind", choices=["node", "relationship"], default="node")

    args = parser.parse_args()

    with Neo4jConnection() as conn:
        if args.command == "list":
            rows = review.list_flagged(conn)
            for row in rows:
                print(json.dumps(row, indent=2, default=str))
            print(f"\n{len(rows)} item(s) awaiting review.")
        elif args.command == "approve":
            review.approve(conn, args.element_id, args.kind)
            print(f"Approved {args.kind} {args.element_id} — flag cleared, data kept.")
        elif args.command == "reject":
            review.reject(conn, args.element_id, args.kind)
            print(f"Rejected {args.kind} {args.element_id} — archived and deleted.")


if __name__ == "__main__":
    main()
