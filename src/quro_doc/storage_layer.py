"""Single path-derivation authority for quro-doc storage.
All other modules obtain filesystem paths through this module.
"""

import os
from pathlib import Path
from typing import Optional


class StorageLayer:
    """Single path-derivation authority for quro-doc storage."""

    def __init__(self, base_root: Optional[str] = None):
        self._base_root = base_root or os.getenv(
            "QURO_STORAGE_ROOT", ".quro_context/docs"
        )

    def resolve_storage_root(self, project: Optional[str] = None) -> str:
        """
        Return the effective storage root for a project.

        Resolution order:
        1. project=None -> self._base_root (legacy single-root, backward compat)
        2. project="quro" -> {self._base_root}/projects/quro/

        Pure path-derivation function. No I/O.
        """
        if project is None:
            return self._base_root
        return os.path.join(self._base_root, "projects", project)

    def list_projects(self) -> list[str]:
        """Enumerate all project directories under projects/."""
        root = self._base_root
        projects_dir = os.path.join(root, "projects")
        if not os.path.isdir(projects_dir):
            return []
        return sorted([
            d for d in os.listdir(projects_dir)
            if os.path.isdir(os.path.join(projects_dir, d))
            and not d.startswith(".")
        ])

    def set_projects_root(self, root: str) -> None:
        """Override the base root (used by Hermes sidecar)."""
        self._base_root = root

    def raw_dir(self, project: Optional[str] = None) -> str:
        return os.path.join(self.resolve_storage_root(project), "raw")

    def docs_dir(self, project: Optional[str] = None) -> str:
        return os.path.join(self.resolve_storage_root(project), "docs")

    def assets_dir(self, project: Optional[str] = None) -> str:
        return os.path.join(self.resolve_storage_root(project), "assets")

    def index_dir(self, project: Optional[str] = None, ns: str = "default") -> str:
        return os.path.join(self.resolve_storage_root(project), "index", ns)

    def jobs_dir(self, project: Optional[str] = None) -> str:
        return os.path.join(self.resolve_storage_root(project), "jobs")


# ── Module-level convenience API ─────────────────────────────────────
#
# `hermes_api.py` and other callers that don't need a custom base_root
# use these module-level functions. They delegate to a global default
# StorageLayer instance initialized from QURO_STORAGE_ROOT at import time.

_default_storage_layer: Optional["StorageLayer"] = None


def _get_default() -> "StorageLayer":
    global _default_storage_layer
    if _default_storage_layer is None:
        _default_storage_layer = StorageLayer()
    return _default_storage_layer


def resolve_storage_root(project: Optional[str] = None) -> str:
    return _get_default().resolve_storage_root(project)


def list_projects() -> list[str]:
    return _get_default().list_projects()
