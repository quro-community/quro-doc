"""quro-doc CLI — add, get, search, mcp, vec."""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quro-doc",
        description="Lightweight Cognitive Document System CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Register subcommands
    from . import add, get, search, mcp, vec, hermes_mcp, okf, materialize

    add.build_parser(sub)
    get.build_parser(sub)
    search.build_parser(sub)
    mcp.build_parser(sub)
    vec.build_parser(sub)
    hermes_mcp.build_parser(sub)
    okf.build_parser(sub)
    materialize.build_parser(sub)

    return parser


def main(argv: list[str] | None = None) -> None:
    # Load .env from current working directory — all config derives from it
    load_dotenv(os.path.join(os.getcwd(), ".env"))

    parser = build_parser()
    args = parser.parse_args(argv)

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
