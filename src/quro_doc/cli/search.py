"""quro-doc search — Search documents in the store."""

from __future__ import annotations

import argparse
import json
import sys
from ..ext.reader import MarkdownReader


def cmd_search(args: argparse.Namespace) -> None:
    query: dict = {}

    query_str = args.query or ""
    if not query_str and not sys.stdin.isatty():
        query_str = sys.stdin.read().strip()

    if not query_str:
        print("Error: search query is required", file=sys.stderr)
        sys.exit(1)

    query["query"] = query_str
    if args.top_k is not None:
        query["top_k"] = args.top_k
    if args.trace_id:
        query["trace_id"] = args.trace_id
    if args.json_input:
        try:
            extra = json.loads(args.json_input)
            query.update(extra)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in --json: {e}", file=sys.stderr)
            sys.exit(1)

    result = MarkdownReader().search(query)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("search", help="Search documents in the store")
    p.add_argument("query", nargs="?", default="", help="Search query text")
    p.add_argument("--top-k", type=int, default=None, help="Number of results to return")
    p.add_argument("--trace-id", help="Trace ID for observability")
    p.add_argument("--json", dest="json_input", help="Extra JSON query fields")
    p.set_defaults(func=cmd_search)
