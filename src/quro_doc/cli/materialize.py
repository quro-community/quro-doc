"""quro-doc materialize — Download pending assets (Phase 3b).

Provides deferred (worker) and direct (run) execution modes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from ..pipelines.materialize_pipeline import (
    run_materialize_pipeline,
    run_materialize_pipeline_for_assets,
)


def cmd_materialize_run(args: argparse.Namespace) -> None:
    """Materialize assets for a specific document (or process pending jobs once)."""
    if args.doc_id:
        result = run_materialize_pipeline(args.doc_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # No doc_id: process all pending materialize_asset jobs once
    from ..storage import get_storage_root

    jobs_dir = os.path.join(get_storage_root(), "jobs")
    if not os.path.isdir(jobs_dir):
        print(json.dumps({"status": "ok", "message": "no jobs directory"}, indent=2))
        return

    processed = 0
    results = []
    for fname in sorted(os.listdir(jobs_dir)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(jobs_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                job = json.load(fh)
        except Exception:
            continue

        if job.get("job_type") != "materialize_asset":
            continue

        doc_id = job.get("target_doc") or job.get("doc_id")
        assets = job.get("payload", {}).get("assets", [])

        print(f"Materializing assets for doc_id={doc_id} ...", file=sys.stderr)
        result = run_materialize_pipeline_for_assets(doc_id, assets)
        results.append(result)
        processed += 1

        # Clean up processed job
        os.remove(path)

    print(json.dumps({
        "status": "ok",
        "jobs_processed": processed,
        "results": results,
    }, indent=2, ensure_ascii=False))


def cmd_materialize_worker(args: argparse.Namespace) -> None:
    """Run as a daemon — poll for materialize_asset jobs continuously."""
    from ..storage import get_storage_root

    poll_interval = args.interval
    print(f"quro materialize worker started (poll={poll_interval}s)", file=sys.stderr)

    while True:
        jobs_dir = os.path.join(get_storage_root(), "jobs")
        processed = False

        if os.path.isdir(jobs_dir):
            for fname in sorted(os.listdir(jobs_dir)):
                if not fname.endswith(".json"):
                    continue
                path = os.path.join(jobs_dir, fname)
                job = None
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        job = json.load(fh)
                except Exception:
                    continue

                if job is None or job.get("job_type") != "materialize_asset":
                    continue

                doc_id = job.get("target_doc") or job.get("doc_id")
                assets = job.get("payload", {}).get("assets", [])

                print(f"[materialize] {doc_id} ({len(assets)} assets)", file=sys.stderr)
                try:
                    result = run_materialize_pipeline_for_assets(doc_id, assets)
                    print(json.dumps(result, ensure_ascii=False))
                except Exception as e:
                    print(f"[materialize] error: {e}", file=sys.stderr)

                os.remove(path)
                processed = True

        if not processed:
            time.sleep(poll_interval)


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "materialize",
        help="Download pending assets (Phase 3b deferred execution)",
    )

    mat_sub = p.add_subparsers(dest="materialize_command", required=True)

    # run
    p_run = mat_sub.add_parser("run", help="Materialize assets for a doc or process pending jobs once")
    p_run.add_argument("--doc-id", default=None, help="Specific doc_id to materialize assets for")
    p_run.set_defaults(func=cmd_materialize_run)

    # worker (polling daemon)
    p_worker = mat_sub.add_parser("worker", help="Run materialize worker daemon — polls job queue continuously")
    p_worker.add_argument(
        "--interval", type=int, default=5,
        help="Poll interval in seconds (default: 5)",
    )
    p_worker.set_defaults(func=cmd_materialize_worker)
