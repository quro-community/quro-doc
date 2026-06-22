"""quro-doc get — Retrieve a document by doc_id."""

from __future__ import annotations

import argparse
import json
from ..ext.reader import MarkdownReader


def cmd_get(args: argparse.Namespace) -> None:
    reader = MarkdownReader()
    result = reader.get(args.doc_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("get", help="Retrieve a document by doc_id")
    p.add_argument("doc_id", help="Document ID to retrieve")
    p.set_defaults(func=cmd_get)
