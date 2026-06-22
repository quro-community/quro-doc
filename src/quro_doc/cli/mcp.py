"""quro-doc mcp — Run the MCP stdio server exposing quro_doc_add and quro_doc_search."""

from __future__ import annotations

import argparse
import sys


def cmd_mcp(args: argparse.Namespace) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
        sys.exit(1)

    from ..ext.reader import PlainTextReader
    from ..ext.writer import PlainTextWriter
    from ..ext.inspector import MetadataInspector

    reader = PlainTextReader()
    writer = PlainTextWriter()
    inspector = MetadataInspector()

    server = FastMCP("quro-doc")

    @server.tool()
    def quro_doc_add(
        file_path: str,
        title: str,
        topic: str,
        intent: str,
        tags: list,
        doc_id: str = None,
        refs: list = None,
        assets: list = None,
        metadata: dict = None,
        source: dict = None,
        git_hash: str = None,
        created_at: str = None,
    ) -> dict:
        """Add a document to the raw store (append-only) and schedule async indexing.

        Args:
            file_path: Path to the local file containing the document body.
            title: Display title of the article (required).
            topic: Main subject area (required).
            intent: Purpose of the article (required, e.g. specification, analysis, how-to).
            tags: List of relevant tags (required, at least one).
            doc_id: Optional document ID for idempotency.
            refs: Optional list of references.
            assets: Optional list of asset references.
            metadata: Optional metadata dict.
            source: Optional source info dict.
            git_hash: Optional git hash.
            created_at: Optional creation timestamp.
        Returns:
            dict with status, doc_id, job_id, message
        """
        import os
        payload = {
            "file_path": file_path,
            "title": title,
            "topic": topic,
            "intent": intent,
            "tags": tags,
            "doc_id": doc_id,
            "refs": refs,
            "assets": assets,
            "metadata": metadata,
            "source": source,
            "git_hash": git_hash,
            "created_at": created_at,
        }
        if file_path:
            payload.setdefault("path", os.path.abspath(file_path))
        payload = {k: v for k, v in payload.items() if v is not None}
        return writer.add(payload)

    @server.tool()
    def quro_doc_search(query: dict) -> list:
        """Search documents in the store.

        Args:
            query: Search query dict with at minimum 'query' (text). Supports
                   top_k, trace_id.
        Returns:
            list of result dicts with doc_id, score, snippet, tags, content
        """
        return reader.search(query)

    @server.tool()
    def quro_doc_get(doc_id: str) -> dict:
        """Retrieve a document by doc_id directly (no semantic search).

        Args:
            doc_id: The document ID to retrieve.
        Returns:
            dict with doc_id, body, meta on success; status='not_found' on miss
        """
        return reader.get(doc_id)

    @server.tool()
    def quro_doc_get_asset(asset_id: str) -> dict:
        """Retrieve a binary asset by asset_id.

        Args:
            asset_id: The asset identifier to retrieve.
        Returns:
            dict with asset_id, data, meta on success; status='not_found' on miss
        """
        return reader.get_asset(asset_id)

    @server.tool()
    def quro_doc_delete_asset(asset_id: str) -> dict:
        """Delete a binary asset by asset_id.

        Args:
            asset_id: The asset identifier to delete.
        Returns:
            dict with status 'deleted' or 'not_found'
        """
        return reader.delete_asset(asset_id)

    @server.tool()
    def quro_doc_list_doc_ids(limit: int = 100, offset: int = 0) -> dict:
        """List all doc-ids with lightweight metadata summaries.

        Args:
            limit: Maximum number of doc summaries to return (1-10000).
            offset: Pagination offset.
        Returns:
            dict with protocol_version, doc_ids, total, has_more, latency_ms
        """
        return inspector.list_doc_ids(limit=limit, offset=offset)

    @server.tool()
    def quro_doc_get_metadata(doc_id: str,
                               metadata_set: list = None) -> dict:
        """Retrieve full metadata for a single doc_id.

        Args:
            doc_id: The document identifier.
            metadata_set: Optional list of metadata field declarations
                          [{key, description, domain, map_to}].
        Returns:
            dict with protocol_version, doc_id, metadata on success;
            status='not_found' on miss
        """
        return inspector.get_metadata(doc_id, metadata_set=metadata_set)

    @server.tool()
    def quro_doc_list_metadata_keys(min_coverage: float = 0.0,
                                      metadata_set: list = None) -> dict:
        """Discover all metadata member field names across all documents.

        Args:
            min_coverage: Minimum fraction of documents that must contain
                          the key (0.0 = show all keys).
            metadata_set: Optional list of metadata field declarations
                          [{key, description, domain, map_to}].
        Returns:
            dict with protocol_version, metadata_keys, total_docs, latency_ms
        """
        return inspector.list_metadata_keys(min_coverage=min_coverage,
                                            metadata_set=metadata_set)

    @server.tool()
    def quro_doc_query_by_metadata(filters: list, limit: int = 100,
                                   offset: int = 0) -> dict:
        """Filter documents by metadata criteria (AND-combined).

        Args:
            filters: List of filter dicts, each with key, operator, value.
                     Operators: eq, neq, contains, gt, gte, lt, lte, exists, in.
            limit: Maximum results to return (1-10000).
            offset: Pagination offset.
        Returns:
            dict with protocol_version, results, total, has_more,
                 filters_applied, latency_ms
        """
        return inspector.query_by_metadata(filters=filters, limit=limit,
                                           offset=offset)

    server.run(transport=args.transport)


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("mcp", help="Run the MCP server (stdio or sse)")
    p.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio",
        help="MCP transport protocol (default: stdio)",
    )
    p.set_defaults(func=cmd_mcp)
