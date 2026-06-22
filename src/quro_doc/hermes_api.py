"""Cross-project entry point for Hermes Agent.
Provides add/search/get/asset/vec-scan with project parameter.
"""

import os
from typing import Optional

from . import storage_layer
from . import storage


def _env_swap(project, fn, *args, **kwargs):
    root = storage_layer.resolve_storage_root(project)
    old = os.environ.get("QURO_STORAGE_ROOT")
    os.environ["QURO_STORAGE_ROOT"] = root
    try:
        return fn(*args, **kwargs)
    finally:
        if old is not None:
            os.environ["QURO_STORAGE_ROOT"] = old
        else:
            del os.environ["QURO_STORAGE_ROOT"]


def hermes_add(project: str, payload: dict, writer=None) -> dict:
    """Add document to a specific project's store."""
    payload["_project"] = project
    if writer is None:
        from .ext.writer import MarkdownWriter
        writer = MarkdownWriter()
    return _env_swap(project, writer.add, payload)


def hermes_search(project: str, query: dict) -> list:
    """Search documents in a specific project's store."""
    query["_project"] = project
    query.setdefault("view", "default")
    from .ext.reader import MarkdownReader
    reader = MarkdownReader()
    return _env_swap(project, reader.search, query)


def hermes_search_all(query: dict) -> list:
    """Fan-out search across all projects, merge results."""
    projects = storage_layer.list_projects()
    if not projects:
        return hermes_search(None, query)
    all_results = []
    for p in projects:
        results = hermes_search(p, query)
        if isinstance(results, str):
            continue
        if not isinstance(results, list):
            continue
        for r in results:
            if isinstance(r, dict):
                r["_project"] = p
        all_results.extend(results)
    all_results.sort(key=lambda r: r.get("score", 0), reverse=True)
    return all_results[:query.get("top_k", 10)]


def hermes_get(project: str, doc_id: str) -> dict:
    """Retrieve a document by doc_id from a specific project's store."""
    from .ext.reader import MarkdownReader
    reader = MarkdownReader()
    return _env_swap(project, reader.get, doc_id)


def hermes_put_asset(project: str, asset_id: str,
                     file_path: str = None,
                     data: bytes = None,
                     content_type: str = "application/octet-stream",
                     writer=None) -> dict:
    """Store a binary asset in a specific project's store.

    file_path takes precedence over data. When file_path is provided,
    Writer reads the file. When data is provided directly (programmatic
    callers), it is passed through to Core.
    """
    if file_path:
        if writer is None:
            from .ext.writer import MarkdownWriter
            writer = MarkdownWriter()
        return _env_swap(project, writer.put_asset,
                         asset_id=asset_id, file_path=file_path,
                         mime_type=content_type)
    from .api import quro_doc_put_asset as _put_asset
    return _env_swap(project, _put_asset,
                     asset_id=asset_id, data=data, content_type=content_type)


def hermes_get_asset(project: str, asset_id: str) -> dict:
    """Retrieve a binary asset from a specific project's store."""
    from .ext.reader import MarkdownReader
    reader = MarkdownReader()
    return _env_swap(project, reader.get_asset, asset_id)


def hermes_delete_asset(project: str, asset_id: str) -> dict:
    """Delete a binary asset from a specific project's store."""
    from .ext.reader import MarkdownReader
    reader = MarkdownReader()
    return _env_swap(project, reader.delete_asset, asset_id)


def hermes_vec_scan(project: Optional[str] = None, **kwargs):
    """Run vector scan for one project or all projects."""
    if project:
        return _vec_scan_project(project, **kwargs)
    for p in storage_layer.list_projects():
        _vec_scan_project(p, **kwargs)


def hermes_list_doc_ids(project: str, limit: int = 100,
                        offset: int = 0) -> dict:
    """List doc-ids with lightweight summaries for a specific project."""
    from .ext.inspector import MetadataInspector
    inspector = MetadataInspector()
    return _env_swap(project, inspector.list_doc_ids, limit=limit,
                     offset=offset)


def hermes_get_metadata(project: str, doc_id: str,
                        metadata_set: Optional[list] = None) -> dict:
    """Retrieve full metadata for a single doc_id in a specific project."""
    from .ext.inspector import MetadataInspector
    inspector = MetadataInspector()
    return _env_swap(project, inspector.get_metadata, doc_id,
                     metadata_set=metadata_set)


def hermes_list_metadata_keys(project: str,
                              min_coverage: float = 0.0,
                              metadata_set: Optional[list] = None) -> dict:
    """Discover metadata keys across all documents in a specific project."""
    from .ext.inspector import MetadataInspector
    inspector = MetadataInspector()
    return _env_swap(project, inspector.list_metadata_keys,
                     min_coverage=min_coverage,
                     metadata_set=metadata_set)


def hermes_query_by_metadata(project: str, filters: list,
                             limit: int = 100, offset: int = 0) -> dict:
    """Filter documents by metadata criteria in a specific project."""
    from .ext.inspector import MetadataInspector
    inspector = MetadataInspector()
    return _env_swap(project, inspector.query_by_metadata,
                     filters=filters, limit=limit, offset=offset)


def _vec_scan_project(project: str, **kwargs):
    """Run vector scan for a single project — index all documents."""
    from .pipelines.index_pipeline import run_index_pipeline
    root = storage_layer.resolve_storage_root(project)
    old = os.environ.get("QURO_STORAGE_ROOT")
    os.environ["QURO_STORAGE_ROOT"] = root
    try:
        seen_ids: set = set()
        for sub in ("docs", "raw"):
            scan_dir = os.path.join(storage.get_storage_root(), sub)
            if not os.path.isdir(scan_dir):
                continue
            txt_files = sorted(f for f in os.listdir(scan_dir) if f.endswith(".txt"))
            for fname in txt_files:
                doc_id = fname[:-4]
                if doc_id in seen_ids:
                    continue
                seen_ids.add(doc_id)
                run_index_pipeline(doc_id)
    finally:
        if old is not None:
            os.environ["QURO_STORAGE_ROOT"] = old
        else:
            del os.environ["QURO_STORAGE_ROOT"]
