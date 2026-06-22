"""QuroDocSource — OKF Source interface adapter backed by quro-doc Hermes APIs.

Implements the OKF Source interface for use by OKF enrichment agents.
list_concepts() routes through hermes_search.
read_concept() routes through hermes_get.
No direct file system or storage access (except fallback enumeration).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ConceptRef:
    """Reference to an OKF concept for the Source interface."""

    doc_id: str
    type: str = ""
    title: str = ""
    description: str = ""


def _extract_inner_meta(meta: dict) -> dict:
    """Extract the inner metadata dict from quro-doc stored metadata."""
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, TypeError):
            return {}
    wrapper = meta.get("meta", {})
    if isinstance(wrapper, str):
        try:
            wrapper = json.loads(wrapper)
        except (json.JSONDecodeError, TypeError):
            return {}
    return wrapper.get("metadata", {})


def _resolve_root(storage_root: Optional[str]) -> str:
    """Resolve the effective storage root from parameter or environment."""
    return storage_root or os.getenv("QURO_STORAGE_ROOT") or ".quro_context/docs"


def _extract_tags(meta: dict) -> list:
    """Extract original OKF tags (strip quro-doc system tags)."""
    wrapper = meta.get("meta", {})
    if isinstance(wrapper, str):
        try:
            wrapper = json.loads(wrapper)
        except (json.JSONDecodeError, TypeError):
            wrapper = {}
    tags = wrapper.get("tags", [])
    if isinstance(tags, list):
        return [t for t in tags if not t.startswith("okf:") and t != "okf"]
    return []


class QuroDocSource:
    """OKF Source interface adapter backed by quro-doc.

    list_concepts() → hermes_search → quro_doc_search → query pipeline.
    read_concept()   → hermes_get   → quro_doc_get   → direct lookup.

    Falls back to full enumeration if search is unavailable.
    """

    def __init__(self, project: str, storage_root: Optional[str] = None):
        """Initialize the source adapter for a specific quro-doc project.

        Args:
            project: quro-doc project name.
            storage_root: Optional override for QURO_STORAGE_ROOT (base root).
        """
        self.project = project
        self._storage_root = storage_root

    def _project_root(self) -> str:
        """Compute the filesystem path for this project's storage root."""
        base = _resolve_root(self._storage_root)
        return os.path.join(base, "projects", self.project)

    def _ensure_base_env(self) -> Optional[str]:
        """Ensure QURO_STORAGE_ROOT is set to the base storage root.

        hermes_* functions call storage_layer.resolve_storage_root(project)
        which appends /projects/{project} to QURO_STORAGE_ROOT. So we must
        ensure QURO_STORAGE_ROOT is the base root, not the project root.
        """
        if self._storage_root:
            old = os.environ.get("QURO_STORAGE_ROOT")
            os.environ["QURO_STORAGE_ROOT"] = self._storage_root
            return old
        return None

    @staticmethod
    def _restore_env(old: Optional[str]) -> None:
        if old is not None:
            os.environ["QURO_STORAGE_ROOT"] = old
        else:
            os.environ.pop("QURO_STORAGE_ROOT", None)

    def list_concepts(self) -> list[ConceptRef]:
        """List all concepts in the project via semantic search.

        Routes through hermes_search for the project.
        Falls back to full enumeration if search returns empty or fails.

        Returns:
            list of ConceptRef. Empty list on failure.
        """
        try:
            from ..hermes_api import hermes_search

            old = self._ensure_base_env()
            try:
                results = hermes_search(
                    self.project,
                    {"query": "*", "top_k": 500, "view": "default"},
                )
            finally:
                self._restore_env(old)

            if results and isinstance(results, list):
                concepts = []
                for r in results:
                    if not isinstance(r, dict):
                        continue
                    concepts.append(ConceptRef(
                        doc_id=r.get("doc_id", ""),
                        type=self._extract_type(r),
                        title=r.get("title", ""),
                        description=r.get("snippet", ""),
                    ))
                if concepts:
                    return concepts

        except Exception:
            pass

        return self._list_all_docs()

    def _list_all_docs(self) -> list[ConceptRef]:
        """Fallback: enumerate all documents in the project via filesystem scan."""
        project_root = self._project_root()

        concepts = []
        seen_ids: set[str] = set()

        for subdir_name in ("docs", "raw"):
            subdir = os.path.join(project_root, subdir_name)
            if not os.path.isdir(subdir):
                continue
            for dirpath, _dirnames, filenames in os.walk(subdir):
                for fname in sorted(filenames):
                    if not fname.endswith(".json"):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(fpath, subdir)
                    doc_id = rel_path[:-5] if rel_path.endswith(".json") else rel_path

                    try:
                        with open(fpath, "r", encoding="utf-8") as fh:
                            data = json.load(fh)
                    except (json.JSONDecodeError, OSError):
                        data = {}

                    stored_doc_id = data.get("doc_id")
                    if stored_doc_id:
                        doc_id = stored_doc_id

                    if doc_id in seen_ids:
                        continue
                    seen_ids.add(doc_id)

                    inner = _extract_inner_meta(data)
                    meta = data.get("meta", {})

                    concepts.append(ConceptRef(
                        doc_id=doc_id,
                        type=inner.get("okf_type", ""),
                        title=inner.get("title") or meta.get("topic", ""),
                        description=inner.get("description", ""),
                    ))
        return concepts

    @staticmethod
    def _extract_type(result: dict) -> str:
        """Extract OKF type from a search result."""
        tags = result.get("tags", [])
        if isinstance(tags, list):
            for tag in tags:
                if tag.startswith("okf:type:"):
                    return tag[len("okf:type:"):]
        meta = result.get("meta", {})
        if isinstance(meta, dict):
            inner = _extract_inner_meta(meta)
            return inner.get("okf_type", "")
        return ""

    def read_concept(self, ref: ConceptRef) -> Optional[dict]:
        """Read a single concept by reference.

        Direct doc_id lookup via hermes_get. No search involved.

        Args:
            ref: ConceptRef with the doc_id to retrieve.

        Returns:
            Frontmatter dict with body, or None if not found.
        """
        try:
            from ..hermes_api import hermes_get

            old = self._ensure_base_env()
            try:
                result = hermes_get(self.project, ref.doc_id)
            finally:
                self._restore_env(old)

            if not result or result.get("status") == "not_found":
                return None

            body = result.get("body", "")
            meta = result.get("meta", {})
            inner = _extract_inner_meta(meta)
            wrapper = meta.get("meta", {}) if isinstance(meta, dict) else {}
            if isinstance(wrapper, str):
                try:
                    wrapper = json.loads(wrapper)
                except (json.JSONDecodeError, TypeError):
                    wrapper = {}

            frontmatter = {
                "doc_id": ref.doc_id,
                "body": body,
            }

            okf_type = inner.get("okf_type")
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
            if isinstance(tags, list):
                okf_tags = [t for t in tags if not t.startswith("okf:") and t != "okf"]
                if okf_tags:
                    frontmatter["tags"] = okf_tags

            timestamp = inner.get("timestamp") or wrapper.get("created_at")
            if timestamp:
                frontmatter["timestamp"] = timestamp

            return frontmatter

        except Exception:
            return None
