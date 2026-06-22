from __future__ import annotations
import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..storage import get_storage_root
from .model import FeedbackEntry


class FeedbackStore:
    def __init__(self, storage_root: str | None = None):
        self.root = Path(storage_root or get_storage_root()) / "feedback"

    def _ensure_dirs(self, doc_id: str) -> Path:
        doc_dir = self.root / "raw" / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir

    def submit(self, payload: dict) -> dict[str, Any]:
        entry = FeedbackEntry.from_payload(payload)
        if not entry.feedback_id or entry.feedback_id.startswith("fb_"):
            entry.feedback_id = f"fb_{uuid.uuid4().hex[:12]}"
        entry.created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        doc_id = entry.target.artifact_id or entry.target.intent_id or "unknown"
        doc_dir = self._ensure_dirs(doc_id)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}_{entry.feedback_id}.json"
        filepath = doc_dir / filename
        filepath.write_text(
            json.dumps(entry.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {"status": "accepted", "feedback_id": entry.feedback_id}

    def list_by_doc(self, doc_id: str) -> list[dict]:
        doc_dir = self.root / "raw" / doc_id
        if not doc_dir.exists():
            return []
        results = []
        for path in sorted(doc_dir.glob("*.json")):
            try:
                results.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return results

    def list_all_raw(self) -> list[dict]:
        raw_dir = self.root / "raw"
        if not raw_dir.exists():
            return []
        results = []
        for doc_dir in sorted(raw_dir.iterdir()):
            if not doc_dir.is_dir():
                continue
            results.extend(self.list_by_doc(doc_dir.name))
        return results

    def list_doc_dirs(self) -> list[str]:
        raw_dir = self.root / "raw"
        if not raw_dir.exists():
            return []
        return sorted(d.name for d in raw_dir.iterdir() if d.is_dir())
