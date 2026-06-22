"""OKF Ingest Pipeline — orchestrate scanning + parsing + transforming + writing
of OKF concepts into quro-doc storage.

Writes are the ONLY side effect. Does not wait for async index jobs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .scanner import scan_bundle
from .parser import parse_frontmatter


def _resolve_root(storage_root: Optional[str]) -> str:
    """Resolve the effective storage root from parameter or environment."""
    return storage_root or os.getenv("QURO_STORAGE_ROOT") or ".quro_context/docs"


@dataclass
class IngestResult:
    """Result of an OKF bundle ingest operation."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    doc_ids: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def _build_add_payload(
    project: str,
    relative_path: str,
    body: str,
    frontmatter: dict,
    internal_links: list[str],
    source_bundle: str,
    raw_frontmatter: str = "",
) -> dict:
    """Transform a parsed OKF concept into a quro_doc_add payload.

    doc_id = {project}/{relative_path} (no .md suffix).
    Tags = merge(OKF frontmatter tags, ["okf"], ["okf:type:{type}"]).
    Metadata preserves okf_type, resource, timestamp, okf_version.
    Stores raw YAML frontmatter for byte-perfect round-trip export.
    """
    doc_id = f"{project}/{relative_path}"
    if doc_id.endswith(".md"):
        doc_id = doc_id[:-3]

    okf_type = frontmatter.get("type", "unknown")
    okf_tags = frontmatter.get("tags", [])
    if isinstance(okf_tags, str):
        okf_tags = [okf_tags]

    tags = list(okf_tags)
    if "okf" not in tags:
        tags.append("okf")
    type_tag = f"okf:type:{okf_type}"
    if type_tag not in tags:
        tags.append(type_tag)

    metadata = {
        "okf_type": okf_type,
        "okf_version": frontmatter.get("okf_version", "v0.1"),
    }

    title = frontmatter.get("title")
    if title:
        metadata["title"] = title

    description = frontmatter.get("description")
    if description:
        metadata["description"] = description

    resource = frontmatter.get("resource")
    if resource:
        metadata["resource"] = resource

    timestamp = frontmatter.get("timestamp")
    if timestamp:
        metadata["timestamp"] = timestamp

    if raw_frontmatter:
        metadata["_raw_frontmatter"] = raw_frontmatter

    source = {
        "bundle": source_bundle,
        "file": relative_path,
        "pipeline": "okf_ingest_v1",
        "okf_version": frontmatter.get("okf_version", "v0.1"),
    }

    created_at = timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    payload = {
        "doc_id": doc_id,
        "body": body,
        "topic": title,
        "tags": tags,
        "refs": internal_links,
        "metadata": metadata,
        "source": source,
        "created_at": created_at,
        "_project": project,
    }

    return payload


def ingest_bundle(
    bundle_path: str,
    project: str,
    storage_root: Optional[str] = None,
) -> IngestResult:
    """Run the full OKF ingest pipeline: scan -> parse -> transform -> quro_doc_add.

    Synchronous. Returns when all writes complete. Does NOT wait for index jobs.
    Idempotent: re-ingest with same bundle skips existing doc_ids.

    Args:
        bundle_path: Path to the OKF bundle directory on disk.
        project: quro-doc project name (maps to projects/{project}/ under storage root).
        storage_root: Optional override for QURO_STORAGE_ROOT.

    Returns:
        IngestResult with total, succeeded, failed, doc_ids, and errors.
    """
    root = _resolve_root(storage_root)
    project_root = os.path.join(root, "projects", project)

    old_env = os.environ.get("QURO_STORAGE_ROOT")
    os.environ["QURO_STORAGE_ROOT"] = project_root

    try:
        from ..ext.writer import MarkdownWriter

        result = IngestResult()

        for entry in scan_bundle(bundle_path):
            result.total += 1

            parsed = parse_frontmatter(entry.raw_content, entry.relative_path)

            payload = _build_add_payload(
                project=project,
                relative_path=entry.relative_path,
                body=parsed.body,
                frontmatter=parsed.frontmatter,
                internal_links=parsed.internal_links,
                source_bundle=os.path.abspath(bundle_path),
                raw_frontmatter=parsed.raw_frontmatter,
            )

            try:
                add_result = MarkdownWriter().add(payload)
                status = add_result.get("status", "")
                doc_id = add_result.get("doc_id", payload["doc_id"])

                if status in ("accepted", "exists"):
                    result.succeeded += 1
                    if doc_id not in result.doc_ids:
                        result.doc_ids.append(doc_id)
                else:
                    result.failed += 1
                    result.errors.append({
                        "file": entry.relative_path,
                        "error": add_result.get("message", "Unknown error"),
                    })
            except Exception as e:
                result.failed += 1
                result.errors.append({
                    "file": entry.relative_path,
                    "error": str(e),
                })

        return result

    finally:
        if old_env is not None:
            os.environ["QURO_STORAGE_ROOT"] = old_env
        else:
            os.environ.pop("QURO_STORAGE_ROOT", None)
