"""quro-doc vec — Vector pipeline commands: index, search, scan, stats."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

from quro_doc.storage import write_raw_doc, ensure_dirs, get_storage_root
from quro_doc.storage_layer import StorageLayer
from quro_doc.pipelines.index_pipeline import run_index_pipeline
from quro_doc.pipelines.query_pipeline import search
from quro_doc.vector_adapter import get_adapter


def cmd_index(args: argparse.Namespace) -> None:
    doc_id = args.doc_id
    run_index_pipeline(doc_id)
    adapter = get_adapter()
    meta = adapter.get_meta()
    print(json.dumps({
        "status": "ok",
        "doc_id": doc_id,
        "vector_count": meta.get("vector_count", 0),
        "adapter": meta.get("adapter"),
    }, indent=2))


def cmd_index_file(args: argparse.Namespace) -> None:
    path = args.path
    if not os.path.exists(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as fh:
        body = fh.read()
    doc_id = args.doc_id or str(uuid.uuid4())
    wrote = write_raw_doc(doc_id=doc_id, body=body, metadata={
        "meta": {
            "source": {"file": os.path.abspath(path)},
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    })
    if not wrote:
        print(f"Doc '{doc_id}' already exists. Use overwrite flag or different id.", file=sys.stderr)
        sys.exit(1)
    try:
        run_index_pipeline(doc_id)
    except Exception as e:
        print(f"Error during indexing: {e}", file=sys.stderr)
        print("Make sure your embedding API is running and EMBEDDING_API_KEY is set.", file=sys.stderr)
        sys.exit(1)
    adapter = get_adapter()
    meta = adapter.get_meta()
    print(json.dumps({
        "status": "ok",
        "doc_id": doc_id,
        "vector_count": meta.get("vector_count", 0),
        "adapter": meta.get("adapter"),
    }, indent=2))


def cmd_scan(args: argparse.Namespace) -> None:
    """Scan raw docs directory and index them."""
    if args.project:
        layer = StorageLayer()
        root = layer.resolve_storage_root(args.project)
        old_env = os.environ.get("QURO_STORAGE_ROOT")
        os.environ["QURO_STORAGE_ROOT"] = root
        try:
            _run_scan(args)
        finally:
            if old_env is not None:
                os.environ["QURO_STORAGE_ROOT"] = old_env
            else:
                del os.environ["QURO_STORAGE_ROOT"]
    else:
        _run_scan(args)


def _run_scan(args: argparse.Namespace) -> None:
    root = get_storage_root()
    namespace = os.getenv("VECTOR_STORE_NAMESPACE", "default")
    state_path = os.path.join(root, "index", namespace, "indexed_docs.json")

    seen_ids: set = set()
    all_doc_ids: list = []
    for sub in ("docs", "raw"):
        scan_dir = os.path.join(root, sub)
        if not os.path.isdir(scan_dir):
            continue
        for fname in sorted(os.listdir(scan_dir)):
            if not fname.endswith(".txt"):
                continue
            doc_id = fname[:-4]
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            all_doc_ids.append(doc_id)

    if not all_doc_ids:
        print(json.dumps({"status": "ok", "message": "No documents found.", "indexed": 0}))
        return

    indexed = set()
    if args.incremental and os.path.exists(state_path):
        with open(state_path) as f:
            indexed = set(json.load(f))

    to_index = [d for d in all_doc_ids if d not in indexed] if args.incremental else list(all_doc_ids)
    skipped = len(all_doc_ids) - len(to_index)

    if args.incremental and not to_index:
        print(json.dumps({"status": "ok", "message": "All documents already indexed.", "indexed": 0, "skipped": skipped}))
        return

    mode = "incremental" if args.incremental else "full"
    print(f"Indexing {len(to_index)} documents ({mode} scan, {skipped} skipped)...", file=sys.stderr)

    success = []
    failed = []
    for i, doc_id in enumerate(to_index):
        try:
            run_index_pipeline(doc_id)
            success.append(doc_id)
            print(f"  [{i+1}/{len(to_index)}] {doc_id} OK", file=sys.stderr)
        except Exception as e:
            failed.append({"doc_id": doc_id, "error": str(e)})
            print(f"  [{i+1}/{len(to_index)}] {doc_id} FAILED: {e}", file=sys.stderr)

    updated = sorted(set(all_doc_ids) if not args.incremental else (indexed | set(success)))
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(updated, f, indent=2)

    result = {
        "status": "ok" if not failed else "partial",
        "indexed": len(success),
        "skipped": skipped,
        "total_raw": len(all_doc_ids),
        "mode": mode,
    }
    if failed:
        result["failed"] = failed
    print(json.dumps(result, indent=2))


def cmd_search(args: argparse.Namespace) -> None:
    query_dict: dict = {"query": args.query, "top_k": args.top_k}
    if args.view:
        query_dict["view"] = args.view
    results = search(query_dict)
    print(json.dumps({
        "query": args.query,
        "total_hits": len(results),
        "results": results,
    }, indent=2, ensure_ascii=False))


def cmd_stats(args: argparse.Namespace) -> None:
    adapter = get_adapter()
    meta = adapter.get_meta()
    print(json.dumps(meta, indent=2))


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("vec", help="Vector pipeline commands: index, search, scan, stats")

    vec_sub = p.add_subparsers(dest="vec_command", required=True)

    # scan
    p_scan = vec_sub.add_parser("scan", help="Scan raw docs directory and index all documents")
    p_scan.add_argument("--incremental", action="store_true", help="Only index new documents (skip already-indexed ones)")
    p_scan.add_argument("--project", default=None, help="Project/tenant name for multi-tenant storage")
    p_scan.set_defaults(func=cmd_scan)

    # index
    p_index = vec_sub.add_parser("index", help="Index an existing raw doc by doc_id")
    p_index.add_argument("doc_id", help="Document ID to index")
    p_index.set_defaults(func=cmd_index)

    # index-file
    p_if = vec_sub.add_parser("index-file", help="Add a text file to raw storage and index it")
    p_if.add_argument("path", help="Path to text file")
    p_if.add_argument("--doc-id", help="Optional doc_id (auto-generated if omitted)")
    p_if.set_defaults(func=cmd_index_file)

    # search
    p_search = vec_sub.add_parser("search", help="Search vector store")
    p_search.add_argument("query", help="Search text")
    p_search.add_argument("--top-k", type=int, default=10, help="Max results (default: 10)")
    p_search.add_argument("--view", default=None, help="View mode: default | standard")
    p_search.set_defaults(func=cmd_search)

    # stats
    p_stats = vec_sub.add_parser("stats", help="Show adapter metadata")
    p_stats.set_defaults(func=cmd_stats)
