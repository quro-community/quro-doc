"""OKF Export Pipeline — reconstruct an OKF bundle directory tree from quro-doc storage.

Reads from quro-doc storage. Writes .md files to output directory.
Round-trip: export of an ingested bundle MUST be diff-identical to original (excluding log.md).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class ExportResult:
    """Result of an OKF bundle export operation."""

    total: int = 0
    written: int = 0
    failed: int = 0
    errors: list[dict] = field(default_factory=list)


def _reconstruct_frontmatter(meta: dict) -> dict:
    """Reconstruct YAML frontmatter fields from quro-doc metadata.

    If the original raw YAML string was preserved during ingest (_raw_frontmatter),
    returns it as a dict with a special key to signal exact reconstruction.
    """
    wrapper = meta.get("meta", {})
    if isinstance(wrapper, str):
        try:
            wrapper = json.loads(wrapper)
        except (json.JSONDecodeError, TypeError):
            wrapper = {}

    inner = wrapper.get("metadata", {})

    frontmatter = {}

    okf_type = inner.get("okf_type") or inner.get("type")
    if okf_type:
        frontmatter["type"] = okf_type

    title = inner.get("title") or wrapper.get("topic")
    if title:
        frontmatter["title"] = title

    description = inner.get("description")
    if description:
        frontmatter["description"] = description

    resource = inner.get("resource")
    if resource:
        frontmatter["resource"] = resource

    tags = wrapper.get("tags", [])
    if tags:
        okf_tags = [t for t in tags if not t.startswith("okf:") and t != "okf"]
        if okf_tags:
            frontmatter["tags"] = okf_tags

    timestamp = inner.get("timestamp") or wrapper.get("created_at")
    if timestamp:
        frontmatter["timestamp"] = timestamp

    return frontmatter


def _build_markdown_file(frontmatter: dict, body: str, raw_frontmatter: str = "") -> str:
    """Build a complete .md file with YAML frontmatter and body.

    If raw_frontmatter is provided (the original YAML string preserved during ingest),
    it is used verbatim for byte-perfect round-trip fidelity.

    Returns the full file content as a string.
    """
    if raw_frontmatter:
        yaml_str = raw_frontmatter.strip()
    elif frontmatter:
        yaml_str = yaml.dump(
            frontmatter,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=4096,
        ).strip()
    else:
        return body

    return f"---\n{yaml_str}\n---\n{body}"


def _generate_index_md(doc_ids: list[str]) -> str:
    """Generate an index.md file listing all concepts in the bundle."""
    lines = ["# Bundle Index\n"]
    for doc_id in sorted(doc_ids):
        display_name = doc_id
        lines.append(f"- [{display_name}]({display_name})")
    lines.append("")
    return "\n".join(lines)


def _resolve_root(storage_root: Optional[str]) -> str:
    """Resolve the effective storage root from parameter or environment."""
    return storage_root or os.getenv("QURO_STORAGE_ROOT") or ".quro_context/docs"


def _enumerate_docs(project: str, storage_root: Optional[str] = None) -> list[str]:
    """List all document doc_ids in a project using quro-doc storage."""
    root = _resolve_root(storage_root)
    project_root = os.path.join(root, "projects", project)

    docs_dir = os.path.join(project_root, "docs")
    raw_dir = os.path.join(project_root, "raw")

    seen_ids: set[str] = set()
    for subdir in (docs_dir, raw_dir):
        if not os.path.isdir(subdir):
            continue
        for dirpath, _dirnames, filenames in os.walk(subdir):
            for fname in sorted(filenames):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(fpath, subdir)
                base_doc_id = rel_path[:-5] if rel_path.endswith(".json") else rel_path
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    doc_id = data.get("doc_id") or base_doc_id
                except (json.JSONDecodeError, OSError):
                    doc_id = base_doc_id
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)

    return sorted(seen_ids)


def export_bundle(
    project: str,
    output_dir: str,
    storage_root: Optional[str] = None,
) -> ExportResult:
    """Reconstruct an OKF bundle directory tree from quro-doc storage.

    Synchronous. Overwrites output_dir if it exists.
    Generates index.md from the document list.

    Args:
        project: quro-doc project name to export.
        output_dir: Directory to write the OKF bundle files to.
        storage_root: Optional override for QURO_STORAGE_ROOT.

    Returns:
        ExportResult with total, written, failed, and errors.
    """
    import shutil

    root = _resolve_root(storage_root)
    project_root = os.path.join(root, "projects", project)

    old_env = os.environ.get("QURO_STORAGE_ROOT")
    os.environ["QURO_STORAGE_ROOT"] = project_root

    result = ExportResult()

    try:
        from ..storage import read_raw_doc

        doc_ids = _enumerate_docs(project, storage_root)
        result.total = len(doc_ids)

        if not doc_ids:
            return result

        out_abs = os.path.abspath(output_dir)
        if os.path.isdir(out_abs):
            shutil.rmtree(out_abs)
        os.makedirs(out_abs, exist_ok=True)

        written_ids = []

        for doc_id in doc_ids:
            try:
                doc = read_raw_doc(doc_id)
                if doc is None:
                    result.failed += 1
                    result.errors.append({
                        "doc_id": doc_id,
                        "error": "Document not found",
                    })
                    continue

                body = doc.get("body", "")
                meta = doc.get("meta", {})

                wrapper = meta.get("meta", {})
                if isinstance(wrapper, str):
                    try:
                        wrapper = json.loads(wrapper)
                    except (json.JSONDecodeError, TypeError):
                        wrapper = {}
                inner = wrapper.get("metadata", {})
                raw_frontmatter = inner.get("_raw_frontmatter", "")

                frontmatter = _reconstruct_frontmatter(meta)
                file_content = _build_markdown_file(frontmatter, body, raw_frontmatter=raw_frontmatter)

                rel_path = doc_id
                if rel_path.startswith(f"{project}/"):
                    rel_path = rel_path[len(project) + 1:]

                md_filename = rel_path
                if not md_filename.endswith(".md"):
                    md_filename = f"{md_filename}.md"

                out_path = os.path.join(out_abs, md_filename)
                out_parent = os.path.dirname(out_path)
                if out_parent != out_abs:
                    os.makedirs(out_parent, exist_ok=True)

                with open(out_path, "w", encoding="utf-8") as fh:
                    fh.write(file_content)

                result.written += 1
                written_ids.append(rel_path)

            except Exception as e:
                result.failed += 1
                result.errors.append({
                    "doc_id": doc_id,
                    "error": str(e),
                })

        index_content = _generate_index_md(written_ids)
        index_path = os.path.join(out_abs, "index.md")
        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write(index_content)

        return result

    finally:
        if old_env is not None:
            os.environ["QURO_STORAGE_ROOT"] = old_env
        else:
            os.environ.pop("QURO_STORAGE_ROOT", None)
