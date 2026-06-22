"""CLI entry point for quro-doc okf ingest and quro-doc okf export.

Pure orchestration — delegates business logic to OKF pipeline modules.
"""

from __future__ import annotations

import argparse
import os
import sys


def cmd_okf_ingest(args: argparse.Namespace) -> None:
    """Handle `quro-doc okf ingest --bundle <path> --project <name>`."""
    bundle_path = args.bundle
    project = args.project
    storage_root = args.storage_root or os.getenv("QURO_STORAGE_ROOT")

    if not os.path.isdir(bundle_path):
        print(f"Error: bundle path not found or not a directory: {bundle_path}", file=sys.stderr)
        sys.exit(1)

    from ..okf.ingest import ingest_bundle

    result = ingest_bundle(bundle_path=bundle_path, project=project, storage_root=storage_root)

    print(f"Ingest complete: {result.succeeded} succeeded, {result.failed} failed, {result.total} total")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for err in result.errors:
            file_path = err.get("file", "unknown")
            error_msg = err.get("error", "unknown error")
            print(f"  - {file_path}: {error_msg}")

    if result.failed > 0:
        sys.exit(1)


def cmd_okf_export(args: argparse.Namespace) -> None:
    """Handle `quro-doc okf export --project <name> --out <dir>`."""
    project = args.project
    output_dir = args.out
    storage_root = args.storage_root or os.getenv("QURO_STORAGE_ROOT")

    from ..okf.export import export_bundle

    result = export_bundle(project=project, output_dir=output_dir, storage_root=storage_root)

    print(f"Export complete: {result.written} written, {result.failed} failed, {result.total} total")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for err in result.errors:
            doc_id = err.get("doc_id", "unknown")
            error_msg = err.get("error", "unknown error")
            print(f"  - {doc_id}: {error_msg}")

    if result.failed > 0:
        sys.exit(1)


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the `okf` subcommand with `ingest` and `export` sub-subcommands."""
    p = subparsers.add_parser("okf", help="OKF bundle ingest and export operations")
    okf_sub = p.add_subparsers(dest="okf_command", required=True)

    ingest_p = okf_sub.add_parser("ingest", help="Ingest an OKF bundle into quro-doc storage")
    ingest_p.add_argument(
        "--bundle", required=True,
        help="Path to the OKF bundle directory",
    )
    ingest_p.add_argument(
        "--project", required=True,
        help="quro-doc project name for this bundle",
    )
    ingest_p.add_argument(
        "--storage-root", default=None,
        help="Override QURO_STORAGE_ROOT (default: from env)",
    )
    ingest_p.set_defaults(func=cmd_okf_ingest)

    export_p = okf_sub.add_parser("export", help="Export a quro-doc project as an OKF bundle")
    export_p.add_argument(
        "--project", required=True,
        help="quro-doc project name to export",
    )
    export_p.add_argument(
        "--out", required=True,
        help="Output directory for the OKF bundle",
    )
    export_p.add_argument(
        "--storage-root", default=None,
        help="Override QURO_STORAGE_ROOT (default: from env)",
    )
    export_p.set_defaults(func=cmd_okf_export)
