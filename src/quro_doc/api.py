"""MCP tool implementations: quro_doc_add, quro_doc_search

These functions are designed to be minimal, easily testable, and
to satisfy the hard constraints from docs/prototypes/00-tasks.md.
"""

import os
import uuid
import re
from typing import Dict, Any
from .storage import write_raw_doc, read_raw_doc, ensure_dirs
from .pipelines.query_pipeline import search as query_pipeline_search
from .protocols.validator import ProtocolValidator
from .events.store import EventStore
from .model import Field, PayloadKey, ResponseKey, MetaKey, RawDocument
from jsonschema import ValidationError

_SAFE_ASSET_ID_RE = re.compile(r'^[a-zA-Z0-9._\-:]+$')

# Fields from RawDocument.to_dict() that are NOT persisted in the storage
# JSON metadata file (doc_id is the filename, body is in the .txt sidecar).
_STORAGE_EXCLUDE = frozenset({Field.DOC_ID, Field.BODY, Field.CONTEXT_FILES})


def _validate_asset_id(asset_id: str) -> None:
    if not asset_id or not _SAFE_ASSET_ID_RE.match(asset_id):
        raise ValueError(f"Invalid asset_id: {asset_id}")


def _read_file_body(file_path: str) -> Dict[str, Any]:
    """Read file at file_path as UTF-8 text.

    Returns {ResponseKey.STATUS: ResponseKey.OK, Field.BODY: content}
    or {ResponseKey.STATUS: ResponseKey.ERROR, ResponseKey.MESSAGE: reason}.
    """
    if not os.path.isfile(file_path):
        return {ResponseKey.STATUS: ResponseKey.ERROR,
                ResponseKey.MESSAGE: f"file_path not found: {file_path}"}
    if os.path.isdir(file_path):
        return {ResponseKey.STATUS: ResponseKey.ERROR,
                ResponseKey.MESSAGE: f"file_path is a directory: {file_path}"}
    if not os.access(file_path, os.R_OK):
        return {ResponseKey.STATUS: ResponseKey.ERROR,
                ResponseKey.MESSAGE: f"file_path not readable: {file_path}"}
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except UnicodeDecodeError:
        return {ResponseKey.STATUS: ResponseKey.ERROR,
                ResponseKey.MESSAGE: f"file_path is not valid UTF-8: {file_path}"}
    except Exception as e:
        return {ResponseKey.STATUS: ResponseKey.ERROR,
                ResponseKey.MESSAGE: f"file_path read failed: {file_path} — {e}"}
    if not content:
        return {ResponseKey.STATUS: ResponseKey.ERROR,
                ResponseKey.MESSAGE: f"file_path is empty: {file_path}"}
    return {ResponseKey.STATUS: ResponseKey.OK, Field.BODY: content}


def _derive_change_type(payload: Dict[str, Any]) -> str:
    """Derive the change_type for event emission from payload fields.

    Priority: supersedes → version_bump, status=deprecated → deprecated,
    status=archived → archived, default → created.
    """
    if payload.get(PayloadKey.SUPERSEDES):
        return "version_bump"
    status = payload.get(PayloadKey.STATUS)
    if status == "deprecated":
        return "deprecated"
    if status == "archived":
        return "archived"
    return "created"


def quro_doc_add(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Add document to raw store (append-only) and schedule async pipelines.

    Accepts 'file_path' in payload — reads file content as document body.
    When file_path is provided, 'body' is silently ignored (file_path takes
    precedence).

    Input: dict with 'body' or 'context_files' or 'file_path'
    Output: {status, doc_id, job_id, message}
    """
    # File path takes precedence over inline body
    file_path = payload.get(PayloadKey.FILE_PATH)
    if file_path:
        result = _read_file_body(file_path)
        if result[ResponseKey.STATUS] == ResponseKey.ERROR:
            return result
        body = result[Field.BODY]
    else:
        body = payload.get(Field.BODY, "")

    context_files = payload.get(Field.CONTEXT_FILES, [])
    if not body and not context_files:
        return {
            ResponseKey.STATUS: ResponseKey.ERROR,
            ResponseKey.MESSAGE: (
                "Either 'body', 'context_files', or 'file_path' required."
            ),
        }

    # Required metadata fields
    missing = []
    title = payload.get(Field.TITLE)
    if not title or not isinstance(title, str) or not title.strip():
        missing.append(Field.TITLE)
    topic = payload.get(Field.TOPIC)
    if not topic or not isinstance(topic, str) or not topic.strip():
        missing.append(Field.TOPIC)
    tags = payload.get(Field.TAGS)
    if not tags or not isinstance(tags, list) or len(tags) == 0:
        missing.append(Field.TAGS)
    intent = payload.get(Field.INTENT)
    if not intent or not isinstance(intent, str) or not intent.strip():
        missing.append(Field.INTENT)
    if missing:
        return {
            ResponseKey.STATUS: ResponseKey.ERROR,
            ResponseKey.MESSAGE: f"Missing required fields: {', '.join(missing)}",
            ResponseKey.MISSING_FIELDS: missing,
        }

    # Protocol boundary validation
    try:
        validator = ProtocolValidator()
        validator.validate_input(payload, "2.0")
    except ValidationError as e:
        return {
            ResponseKey.STATUS: ResponseKey.ERROR,
            ResponseKey.MESSAGE: str(e.message),
            ResponseKey.VALIDATION_ERRORS: [e.message],
        }

    # Determine doc_id (support caller-provided id for idempotency)
    doc_id = payload.get(Field.DOC_ID) or str(uuid.uuid4())

    # Construct the Kernel entity — this is the single point where a RawDocument
    # is created from payload data.  All downstream code consumes the typed object
    # or its dict representation rather than guessing the dict shape.
    doc = RawDocument.new(
        body=body,
        doc_id=doc_id,
        title=title,
        topic=topic,
        intent=intent,
        tags=payload.get(Field.TAGS, []),
        context_files=payload.get(Field.CONTEXT_FILES, []),
        refs=payload.get(Field.REFS, []),
        assets=payload.get(Field.ASSETS, []),
        metadata=payload.get(Field.METADATA, {}),
        source=payload.get(Field.SOURCE, {}),
        path=payload.get(Field.PATH),
        git_hash=payload.get(Field.GIT_HASH),
        created_at=payload.get(Field.CREATED_AT),
    )

    # Build storage metadata: RawDocument fields (minus exclusions)
    # + protocol-level keys that are not part of RawDocument.
    doc_dict = doc.to_dict()
    storage_metadata = {
        k: v for k, v in doc_dict.items() if k not in _STORAGE_EXCLUDE
    }
    storage_metadata[PayloadKey.STATUS] = payload.get(PayloadKey.STATUS)
    storage_metadata[PayloadKey.VERSION] = payload.get(PayloadKey.VERSION)
    storage_metadata[PayloadKey.SUPERSEDES] = payload.get(PayloadKey.SUPERSEDES)

    # Try write raw (append-only). If already exists, return exists (idempotent)
    wrote = write_raw_doc(
        doc_id=doc_id, body=doc.body,
        metadata={MetaKey.META: storage_metadata},
    )
    if not wrote:
        return {
            ResponseKey.STATUS: ResponseKey.EXISTS,
            ResponseKey.DOC_ID: doc_id,
            ResponseKey.MESSAGE: "Document already exists. No new write performed.",
            ResponseKey.PROTOCOL_VERSION: "2.0.0-draft",
        }

    # Emit change event (best-effort, never blocks write)
    try:
        event_store = EventStore()
        change_type = _derive_change_type(payload)
        summary = f"Document {change_type}: {title}"
        if payload.get(PayloadKey.VERSION):
            summary += f" (v{payload[PayloadKey.VERSION]})"
        event_store.emit(doc_id, change_type, summary)
    except Exception:
        pass

    return {
        ResponseKey.STATUS: ResponseKey.ACCEPTED,
        ResponseKey.DOC_ID: doc_id,
        ResponseKey.MESSAGE: "Document accepted.",
        ResponseKey.PROTOCOL_VERSION: "2.0.0-draft",
    }


def quro_doc_search(query: Dict[str, Any]) -> Any:
    """Multi-level search:

    - Uses query pipeline (vector retriever + context assembler) when adapter
      available.
    - Falls back to raw full-text scan when no vector adapter or query doesn't
      need vectors.
    - Supports view parameter: "default" (JSON), "standard" (TXT), "debug"
      (verbose).
    """
    ensure_dirs()
    results = query_pipeline_search(query)

    if isinstance(results, list):
        try:
            validator = ProtocolValidator()
            validator.validate_output(results, "2.0")
        except ValidationError:
            pass

    return results


def quro_doc_get(doc_id: str) -> Dict[str, Any]:
    """Retrieve a document by doc_id from the current store.

    Direct lookup — bypasses the semantic search pipeline.
    Wraps storage.read_raw_doc().

    Returns:
        {"doc_id": str, "body": str, "meta": dict} on success
        {"status": "not_found", "doc_id": str} when doc_id not found
    """
    result = read_raw_doc(doc_id)
    if result is None:
        return {ResponseKey.STATUS: ResponseKey.NOT_FOUND,
                ResponseKey.DOC_ID: doc_id}
    result[ResponseKey.PROTOCOL_VERSION] = "2.0.0-draft"
    return result


def quro_doc_put_asset(
    asset_id: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> Dict[str, Any]:
    """Store a binary asset (image, PDF, etc.) in the asset store.

    Returns:
        {"status": "accepted", "asset_id": str} on success
        {"status": "exists", "asset_id": str} if already present
    """
    _validate_asset_id(asset_id)
    from .storage import put_asset
    wrote = put_asset(asset_id=asset_id, data=data, content_type=content_type)
    if not wrote:
        return {ResponseKey.STATUS: ResponseKey.EXISTS,
                ResponseKey.ASSET_ID: asset_id}
    return {ResponseKey.STATUS: ResponseKey.ACCEPTED,
            ResponseKey.ASSET_ID: asset_id}


def quro_doc_get_asset(asset_id: str) -> Dict[str, Any]:
    """Retrieve a binary asset by asset_id.

    Returns:
        {"asset_id": str, "data": bytes, "meta": dict} on success
        {"status": "not_found", "asset_id": str} on miss
    """
    _validate_asset_id(asset_id)
    from .storage import get_asset
    result = get_asset(asset_id)
    if result is None:
        return {ResponseKey.STATUS: ResponseKey.NOT_FOUND,
                ResponseKey.ASSET_ID: asset_id}
    return result


def quro_doc_delete_asset(asset_id: str) -> Dict[str, Any]:
    """Delete a binary asset by asset_id.

    Returns:
        {"status": "deleted", "asset_id": str} on success
        {"status": "not_found", "asset_id": str} on miss
    """
    _validate_asset_id(asset_id)
    from .storage import delete_asset
    deleted = delete_asset(asset_id)
    if not deleted:
        return {ResponseKey.STATUS: ResponseKey.NOT_FOUND,
                ResponseKey.ASSET_ID: asset_id}
    return {ResponseKey.STATUS: ResponseKey.DELETED,
            ResponseKey.ASSET_ID: asset_id}
