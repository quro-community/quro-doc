from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import QuroConfig
from ..storage import get_storage_root


class AlignmentStore:
    def __init__(self, config: QuroConfig | None = None):
        self.config = config or QuroConfig.load()
        self.root = Path(self.config.storage_root or get_storage_root()) / "alignment"

    def _ensure_dir(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def write_found(self, doc_id: str, match: dict) -> bool:
        self._ensure_dir()
        match_data = {
            "type": "quro.alignment.found",
            "pipeline_run_id": f"al_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            "new_doc_id": doc_id,
            "matched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "matches": [match],
        }
        path = self.root / f"{doc_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            existing["matches"].extend(match_data["matches"])
            path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            path.write_text(json.dumps(match_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def list_aligned_ids(self) -> set[str]:
        if not self.root.exists():
            return set()
        return {p.stem for p in self.root.glob("*.json")}

    def load_all_results(self) -> list[dict]:
        if not self.root.exists():
            return []
        results = []
        for path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append(data)
            except Exception:
                continue
        return results

    def count_all_matches(self) -> int:
        total = 0
        for result in self.load_all_results():
            total += len(result.get("matches", []))
        return total
