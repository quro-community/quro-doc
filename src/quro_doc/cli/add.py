"""quro-doc add — Add a document to the raw store."""

from __future__ import annotations

import argparse
import json
import os
import sys
from ..ext.writer import MarkdownWriter


def cmd_add(args: argparse.Namespace) -> None:
    payload: dict = {}

    # Build payload from structured CLI flags
    if args.body_file:
        payload["file_path"] = args.body_file
        payload.setdefault("path", os.path.abspath(args.body_file))
    if args.body:
        payload["body"] = args.body
    if args.title:
        payload["title"] = args.title
    if args.topic:
        payload["topic"] = args.topic
    if args.classification:
        payload["classification"] = args.classification
    payload["summary"] = args.summary
    if args.doc_id:
        payload["doc_id"] = args.doc_id
    if args.tags:
        payload["tags"] = args.tags
    if args.file:
        for f in args.file:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    content = fh.read()
            except Exception as e:
                print(f"Error reading {f}: {e}", file=sys.stderr)
                sys.exit(1)
            payload.setdefault("context_files", []).append(
                {"path": f, "content": content}
            )
    if args.json_input:
        try:
            extra = json.loads(args.json_input)
            payload.update(extra)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in --json: {e}", file=sys.stderr)
            sys.exit(1)

    # If nothing provided, try reading body from stdin
    if not payload.get("body") and not payload.get("file_path") and not payload.get("context_files") and not sys.stdin.isatty():
        payload["body"] = sys.stdin.read()

    result = MarkdownWriter().add(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("add", help="Add a document to the raw store")
    p.add_argument("--doc-id", help="Optional doc_id for idempotency")
    p.add_argument("--body", help="Document body text")
    p.add_argument("--body-file", help="Path to file containing document body (takes precedence over --body)")
    p.add_argument("--title", help="Display title of the article (required)")
    p.add_argument("--topic", help="Main subject area (required)")
    p.add_argument("--classification", help="Document type: specification, analysis, how-to, reference, design, tutorial, troubleshooting, overview, api-reference, configuration, testing, deployment, security, performance, migration (required)")
    p.add_argument("--summary", help="Concise description of what the document covers (required, max 200 chars)")
    p.add_argument("--tag", dest="tags", action="append", default=[], help="Tag (required, can be repeated)")
    p.add_argument("--file", action="append", default=[], help="Context file path (can be repeated)")
    p.add_argument("--json", dest="json_input", help="Extra JSON payload fields")
    p.set_defaults(func=cmd_add)
