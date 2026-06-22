"""EventStore — file-based event emission for change tracking.

IMSPEC: Must NOT import registry/, pipelines/, workers/.
Writes only to {project_root}/events/{date}/event-{seq}.json
"""
from __future__ import annotations

import json
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..storage import get_storage_root, ensure_dirs

VALID_CHANGE_TYPES = frozenset({
    "created",
    "updated",
    "deprecated",
    "archived",
    "version_bump",
})


class EventStore:
    """Emit and query change events for artifacts.

    Events are write-once per file; emit never overwrites existing files.
    """

    def __init__(self, storage_root: Optional[str] = None):
        self._storage_root = storage_root or get_storage_root()
        ensure_dirs(self._storage_root)

    def _events_dir(self, date: Optional[str] = None) -> Path:
        base = Path(self._storage_root) / "events"
        if date is not None:
            return base / date
        return base

    def emit(self, artifact_id: str, change_type: str, summary: str) -> str:
        """Emit a change event. Creates a new file per event, never overwrites.

        Args:
            artifact_id: The artifact this event concerns.
            change_type: One of VALID_CHANGE_TYPES.
            summary: Human-readable description of the change.

        Returns the event_id (filename stem).

        Raises ValueError if change_type is invalid.
        """
        if change_type not in VALID_CHANGE_TYPES:
            raise ValueError(
                f"Invalid change_type '{change_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_CHANGE_TYPES))}"
            )
        ensure_dirs(self._storage_root)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        events_dir = self._events_dir(date_str)
        events_dir.mkdir(parents=True, exist_ok=True)
        seq = int(time.time() * 1_000_000)
        event_id = f"event-{seq}"
        path = events_dir / f"{event_id}.json"
        event = {
            "event_id": event_id,
            "artifact_id": artifact_id,
            "change_type": change_type,
            "summary": summary,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
        return event_id

    def query(self, artifact_id: Optional[str] = None, since: Optional[str] = None) -> list[dict]:
        """Query events, optionally filtered by artifact_id and/or since timestamp."""
        ensure_dirs(self._storage_root)
        results: list[dict] = []
        events_root = self._events_dir()
        if not events_root.is_dir():
            return results
        for date_dir in sorted(events_root.iterdir()):
            if not date_dir.is_dir():
                continue
            for f in sorted(date_dir.glob("event-*.json")):
                try:
                    event = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if artifact_id is not None and event.get("artifact_id") != artifact_id:
                    continue
                if since is not None and event.get("timestamp", "") <= since:
                    continue
                results.append(event)
        return results
