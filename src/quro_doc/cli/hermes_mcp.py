"""quro-doc hermes-mcp — Hermes-specific MCP server for cross-project operations.

Default hidden from public MCP (separate endpoint).
Hermes Agent connects to this to manage knowledge across all projects.

Tools exposed:
  hermes_add             Add document to a specific project
  hermes_search          Search within a specific project
  hermes_search_all      Fan-out search across all projects
  hermes_get             Retrieve a document by doc_id from a specific project
  hermes_put_asset       Store a binary asset in a specific project
  hermes_get_asset       Retrieve a binary asset from a specific project
  hermes_delete_asset    Delete a binary asset from a specific project
  hermes_vec_scan        Vector scan one or all projects
"""

from __future__ import annotations

import argparse
import sys
import json
import os


def _default_projects_root() -> str:
    explicit = os.getenv("QURO_PROJECTS_ROOT")
    if explicit:
        return explicit
    base = os.getenv("QURO_STORAGE_ROOT", ".quro_context/docs")
    return os.path.join(base, "projects")


def cmd_hermes_mcp(args: argparse.Namespace) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
        sys.exit(1)

    projects_root = args.projects_root or _default_projects_root()
    base_root = os.path.dirname(projects_root)
    os.environ["QURO_STORAGE_ROOT"] = base_root

    from .. import storage_layer as _sl_mod
    _sl_mod._default_storage_layer = None

    from ..ext.writer import MarkdownWriter

    promise_model = _build_promise_model()
    _writer = MarkdownWriter(promise_model=promise_model)

    from ..hermes_api import (
        hermes_add as _hermes_add,
        hermes_search as _hermes_search,
        hermes_search_all as _hermes_search_all,
        hermes_get as _hermes_get,
        hermes_vec_scan as _hermes_vec_scan,
        hermes_put_asset as _hermes_put_asset,
        hermes_get_asset as _hermes_get_asset,
        hermes_delete_asset as _hermes_delete_asset,
        hermes_list_doc_ids as _hermes_list_doc_ids,
        hermes_get_metadata as _hermes_get_metadata,
        hermes_list_metadata_keys as _hermes_list_metadata_keys,
        hermes_query_by_metadata as _hermes_query_by_metadata,
    )
    from ..storage_layer import list_projects as _list_projects

    server = FastMCP("hermes-quro-doc")

    @server.tool()
    def hermes_add(project: str, file_path: str, title: str, topic: str,
                   classification: str, summary: str, tags: list, doc_id: str = None,
                   refs: list = None, assets: list = None,
                   metadata: dict = None, source: dict = None,
                   git_hash: str = None, created_at: str = None) -> str:
        import os
        payload = {
            "file_path": file_path, "title": title, "topic": topic,
            "classification": classification, "summary": summary, "tags": tags, "doc_id": doc_id,
            "refs": refs, "assets": assets,
            "metadata": metadata, "source": source,
            "git_hash": git_hash, "created_at": created_at,
        }
        if file_path:
            payload.setdefault("path", os.path.abspath(file_path))
        payload = {k: v for k, v in payload.items() if v is not None}
        result = _hermes_add(project, payload, writer=_writer)
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def hermes_search(project: str, query: dict) -> str:
        result = _hermes_search(project, query)
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def hermes_search_all(query: dict) -> str:
        result = _hermes_search_all(query)
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def hermes_get(project: str, doc_id: str) -> str:
        result = _hermes_get(project, doc_id)
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def hermes_vec_scan(project: str | None = None) -> str:
        if project:
            _hermes_vec_scan(project)
            result = {project: "scanned"}
        else:
            result = {}
            for p in _list_projects():
                _hermes_vec_scan(p)
                result[p] = "scanned"
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def hermes_put_asset(project: str, asset_id: str, file_path: str,
                         mime_type: str = "application/octet-stream") -> str:
        """Store a binary asset in a specific project.

        Args:
            project: Project namespace.
            asset_id: The asset identifier.
            file_path: Path to the local file to store.
            mime_type: Optional MIME type (default: application/octet-stream).
        """
        result = _hermes_put_asset(project, asset_id=asset_id,
                                   file_path=file_path, mime_type=mime_type,
                                   writer=_writer)
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def hermes_get_asset(project: str, asset_id: str) -> str:
        """Retrieve a binary asset from a specific project."""
        result = _hermes_get_asset(project, asset_id)
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def hermes_delete_asset(project: str, asset_id: str) -> str:
        """Delete a binary asset from a specific project."""
        result = _hermes_delete_asset(project, asset_id)
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def hermes_list_doc_ids(project: str, limit: int = 100,
                            offset: int = 0) -> str:
        result = _hermes_list_doc_ids(project, limit=limit, offset=offset)
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def hermes_get_metadata(project: str, doc_id: str,
                            metadata_set: list = None) -> str:
        result = _hermes_get_metadata(project, doc_id,
                                       metadata_set=metadata_set)
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def hermes_list_metadata_keys(project: str,
                                  min_coverage: float = 0.0,
                                  metadata_set: list = None) -> str:
        result = _hermes_list_metadata_keys(project,
                                            min_coverage=min_coverage,
                                            metadata_set=metadata_set)
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def hermes_query_by_metadata(project: str, filters: list,
                                 limit: int = 100, offset: int = 0) -> str:
        result = _hermes_query_by_metadata(project, filters=filters,
                                           limit=limit, offset=offset)
        return json.dumps(result, ensure_ascii=False)

    server.run(transport=args.transport)


def _build_promise_model():
    """Try Aria2Crawler -> HttpCrawler -> None. Graceful degradation."""
    try:
        from ..materializers.aria2_crawler import Aria2Crawler
        from ..helpers.asset_promise import AssetPromiseModel
        crawler = Aria2Crawler()
        print("Aria2Crawler initialized", file=sys.stderr)
        return AssetPromiseModel(crawler=crawler)
    except Exception as e:
        print(f"Aria2Crawler unavailable ({e}), trying HttpCrawler", file=sys.stderr)
    try:
        from ..materializers.http_crawler import HttpCrawler
        from ..helpers.asset_promise import AssetPromiseModel
        crawler = HttpCrawler()
        print("HttpCrawler initialized", file=sys.stderr)
        return AssetPromiseModel(crawler=crawler)
    except Exception as e:
        print(f"HttpCrawler unavailable ({e}), falling back to no crawler", file=sys.stderr)
    from ..helpers.asset_promise import AssetPromiseModel
    return AssetPromiseModel()


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "hermes-mcp",
        help="Run the Hermes-specific MCP server (cross-project tools)",
    )
    p.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport protocol (default: stdio)",
    )
    p.add_argument(
        "--projects-root",
        default=None,
        help="Root dir containing project dirs (overrides QURO_PROJECTS_ROOT / QURO_STORAGE_ROOT/projects)",
    )
    p.set_defaults(func=cmd_hermes_mcp)
