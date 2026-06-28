"""Core data model for QuroDoc (RawDocument)"""

from dataclasses import dataclass, asdict, fields
from typing import List, Dict, Optional
from datetime import datetime, timezone
import uuid


class Field:
    """RawDocument field name constants — single source of truth for dict-key access.

    Every consumer that reads/writes RawDocument data as a dict MUST use these
    constants rather than bare string literals.  This eliminates the implicit
    schema coupling that causes silent data loss when a field is renamed.
    """

    DOC_ID: str = "doc_id"
    TITLE: str = "title"
    TOPIC: str = "topic"
    BODY: str = "body"
    CLASSIFICATION: str = "classification"
    SUMMARY: str = "summary"
    CONTEXT_FILES: str = "context_files"
    TAGS: str = "tags"
    REFS: str = "refs"
    ASSETS: str = "assets"
    METADATA: str = "metadata"
    SOURCE: str = "source"
    PATH: str = "path"
    GIT_HASH: str = "git_hash"
    CREATED_AT: str = "created_at"

    # Fields that must be non-empty for document creation
    REQUIRED: frozenset = frozenset({TITLE, TOPIC, TAGS, CLASSIFICATION, SUMMARY})

    # Computed lazily — set of all field names validated against the dataclass
    _all: frozenset | None = None

    @classmethod
    def all(cls) -> frozenset:
        """Return the set of all RawDocument field names (validated at import time)."""
        if cls._all is None:
            cls._all = frozenset(f.name for f in fields(RawDocument))
        return cls._all


class PayloadKey:
    """Protocol-level payload keys not mapped to RawDocument fields.

    These keys appear in the MCP tool payload but are *not* persisted as
    RawDocument fields — they control protocol behaviour (versioning,
    lifecycle state, file ingestion).
    """

    STATUS: str = "status"
    VERSION: str = "version"
    SUPERSEDES: str = "supersedes"
    FILE_PATH: str = "file_path"


class ResponseKey:
    """Keys and status values used in API response dicts."""

    STATUS: str = "status"
    DOC_ID: str = "doc_id"
    MESSAGE: str = "message"
    MISSING_FIELDS: str = "missing_fields"
    PROTOCOL_VERSION: str = "protocol_version"
    VALIDATION_ERRORS: str = "validation_errors"
    ASSET_ID: str = "asset_id"

    # Status *values* (semantically distinct from the key "status")
    ERROR: str = "error"
    OK: str = "ok"
    ACCEPTED: str = "accepted"
    EXISTS: str = "exists"
    NOT_FOUND: str = "not_found"
    DELETED: str = "deleted"


class MetaKey:
    """Storage-layer meta-wrapper key.

    In the current storage format the JSON file stores
    ``{"meta": <document-metadata-dict>}``.  When read back through
    ``storage.read_raw_doc`` the outer envelope becomes
    ``{"doc_id": ..., "body": ..., "meta": {"meta": <document-metadata-dict>}}``.
    Consumers that want the inner document metadata unwrap one level of ``"meta"``.
    """

    META: str = "meta"


@dataclass
class RawDocument:
    doc_id: str
    title: Optional[str]
    topic: Optional[str]
    body: str
    classification: Optional[str]
    summary: Optional[str]
    context_files: List[str]
    tags: List[str]
    refs: List[Dict]
    assets: List[Dict]
    metadata: Dict
    source: Dict
    path: Optional[str]
    git_hash: Optional[str]
    created_at: str

    @staticmethod
    def new(body: str, **kwargs) -> "RawDocument":
        doc_id = kwargs.get("doc_id") or str(uuid.uuid4())
        created_at = kwargs.get("created_at") or (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        return RawDocument(
            doc_id=doc_id,
            title=kwargs.get("title"),
            topic=kwargs.get("topic"),
            body=body,
            classification=kwargs.get("classification"),
            summary=kwargs.get("summary"),
            context_files=kwargs.get("context_files", []),
            tags=kwargs.get("tags", []),
            refs=kwargs.get("refs", []),
            assets=kwargs.get("assets", []),
            metadata=kwargs.get("metadata", {}),
            source=kwargs.get("source", {}),
            path=kwargs.get("path"),
            git_hash=kwargs.get("git_hash"),
            created_at=created_at,
        )

    def to_dict(self):
        return asdict(self)