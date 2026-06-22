"""ConsumerRegistry — file-based registration of protocol consumers.

IMSPEC: Must NOT import pipelines/, workers/.
Writes only to {project_root}/registry/{consumer_id}.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from ..storage import get_storage_root, ensure_dirs


class ConsumerRegistry:
    """Tracks which consumers depend on which protocol IDs.

    Each consumer is a JSON file in registry/ declaring the protocols it consumes.
    """

    def __init__(self, storage_root: Optional[str] = None):
        self._storage_root = storage_root or get_storage_root()
        ensure_dirs(self._storage_root)

    def _registry_path(self, consumer_id: Optional[str] = None) -> Path:
        base = Path(self._storage_root) / "registry"
        if consumer_id is not None:
            return base / f"{consumer_id}.json"
        return base

    def register(self, consumer_id: str, consumes: list[str]) -> str:
        """Register a consumer with its consumed protocol IDs.

        Creates {consumer_id}.json in registry/. Returns consumer_id.
        """
        ensure_dirs(self._storage_root)
        path = self._registry_path(consumer_id)
        data = {
            "consumer_id": consumer_id,
            "consumes": consumes,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return consumer_id

    def get_reverse_dependencies(self, protocol_id: str) -> list[str]:
        """Scan all registry files, return consumers that declare protocol_id."""
        ensure_dirs(self._storage_root)
        consumers: list[str] = []
        registry_dir = self._registry_path()
        if not registry_dir.is_dir():
            return consumers
        for f in sorted(registry_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if protocol_id in data.get("consumes", []):
                    consumers.append(data.get("consumer_id", f.stem))
            except Exception:
                continue
        return consumers
