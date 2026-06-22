from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import QuroConfig
from ..storage import get_storage_root
from ..artifacts.store import ArtifactStore
from .store import AlignmentStore


class IncrementalAlignmentScanner:
    def __init__(self, config: QuroConfig | None = None):
        self.config = config or QuroConfig.load()
        self.artifact_store = ArtifactStore(self.config)
        self.alignment_store = AlignmentStore(self.config)

    def run_scan(
        self,
        batch_size: int = 10,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if not self.config.incremental_alignment_enabled:
            return {"status": "disabled"}

        resolved = self._load_latest_resolved()
        globally_missing = [e for e in resolved if e.get("coverage_state") == "globally_missing"]
        if not globally_missing:
            return {"status": "ok", "message": "no gaps to fill"}

        all_docs = self._discover_raw_docs()
        aligned_docs = self.alignment_store.list_aligned_ids()
        unaligned = [d for d in all_docs if d not in aligned_docs]

        matches = []
        for doc_id in unaligned[:batch_size]:
            body = self._load_doc_body(doc_id)
            if not body:
                continue
            for gap in globally_missing:
                if _intent_matches_token(gap.get("intent_id", ""), body):
                    matches.append({
                        "intent_id": gap["intent_id"],
                        "new_doc_id": doc_id,
                        "new_question_text": gap.get("canonical_question", ""),
                        "previously_missing_in_chunk": gap.get("source_chunk_ref", ""),
                        "match_level": "token",
                        "confidence": 0.85,
                    })
                elif _intent_matches_llm_fallback(gap.get("intent_id", ""), body, self.config):
                    matches.append({
                        "intent_id": gap["intent_id"],
                        "new_doc_id": doc_id,
                        "new_question_text": gap.get("canonical_question", ""),
                        "previously_missing_in_chunk": gap.get("source_chunk_ref", ""),
                        "match_level": "llm",
                        "confidence": 0.70,
                    })

        created = 0
        if not dry_run:
            for match in matches:
                self.alignment_store.write_found(match["new_doc_id"], match)
                created += 1

        total_matches = self.alignment_store.count_all_matches()
        threshold = self.config.alignment_re_resolve_threshold
        re_resolve_triggered = total_matches >= threshold

        return {
            "status": "ok",
            "docs_scanned": len(unaligned),
            "matches_found": len(matches),
            "artifacts_created": created,
            "total_accumulated_matches": total_matches,
            "re_resolve_triggered": re_resolve_triggered,
        }

    def _load_latest_resolved(self) -> list[dict]:
        artifacts = self.artifact_store.list_by_type("quro.coverage.resolved")
        if not artifacts:
            return []
        latest = max(
            artifacts,
            key=lambda a: a.created_at or datetime.min.replace(tzinfo=timezone.utc),
        )
        return json.loads(latest.content)

    def _discover_raw_docs(self) -> list[str]:
        raw_dir = Path(self.config.storage_root or get_storage_root()) / "raw"
        if not raw_dir.exists():
            return []
        return sorted(set(
            p.stem for p in raw_dir.glob("*.txt")
        ))

    def _load_doc_body(self, doc_id: str) -> str | None:
        raw_dir = Path(self.config.storage_root or get_storage_root()) / "raw"
        txt_path = raw_dir / f"{doc_id}.txt"
        if not txt_path.exists():
            return None
        return txt_path.read_text(encoding="utf-8")


def _intent_matches_token(intent_id: str, body: str) -> bool:
    tokens = set(_tokenize_intent(intent_id))
    if not tokens:
        return False
    body_lower = body.lower()
    overlap = sum(1 for t in tokens if t in body_lower)
    return overlap >= 2


def _tokenize_intent(intent_id: str) -> list[str]:
    parts = re.split(r"[.\-_/]", intent_id)
    return [p.lower() for p in parts if len(p) > 1]


def _intent_matches_llm_fallback(intent_id: str, body: str, config: QuroConfig) -> bool:
    return False
