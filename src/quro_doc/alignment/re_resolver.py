from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any

from ..config import QuroConfig
from ..artifacts.store import ArtifactStore, Artifact
from ..storage import get_storage_root
from .store import AlignmentStore


class CoverageReResolver:
    def __init__(self, config: QuroConfig | None = None):
        self.config = config or QuroConfig.load()
        self.artifact_store = ArtifactStore(self.config)
        self.alignment_store = AlignmentStore(self.config)

    def run(self) -> dict[str, Any]:
        all_aligned = self.alignment_store.load_all_results()
        affected_intents: set[str] = set()
        for result in all_aligned:
            for match in result.get("matches", []):
                iid = match.get("intent_id", "")
                if iid:
                    affected_intents.add(iid)

        if not affected_intents:
            return {"status": "ok", "message": "no intents to re-resolve"}

        resolved_artifacts = self.artifact_store.list_by_type("quro.coverage.resolved")
        if not resolved_artifacts:
            return {"status": "ok", "message": "no resolved artifact to update"}

        latest = max(
            resolved_artifacts,
            key=lambda a: a.created_at or datetime.min.replace(tzinfo=timezone.utc),
        )
        entries = json.loads(latest.content)

        updated = []
        changed = 0
        matched_docs_by_intent: dict[str, list[str]] = {}
        for aligned_result in all_aligned:
            for match in aligned_result.get("matches", []):
                miid = match.get("intent_id", "")
                mdoc = match.get("new_doc_id", "")
                if miid and mdoc:
                    matched_docs_by_intent.setdefault(miid, []).append(mdoc)

        for entry in entries:
            iid = entry.get("intent_id", "")
            if iid in affected_intents and entry.get("coverage_state") == "globally_missing":
                aligned_docs = matched_docs_by_intent.get(iid, [])
                if aligned_docs:
                    entry["coverage_state"] = "globally_answered"
                    entry["answered_in_chunks"] = list(set(
                        entry.get("answered_in_chunks", []) + aligned_docs
                    ))
                    entry["discoverability_notes"] = f"filled by alignment: {', '.join(aligned_docs)}"
                    changed += 1
            updated.append(entry)

        if changed == 0:
            return {"status": "ok", "message": "no entries changed", "intents_checked": len(affected_intents)}

        new_artifact = Artifact(
            artifact_id=f"cr_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            artifact_type="quro.coverage.resolved",
            schema_version="1.0",
            kind="evidence",
            source_docs=list(set(e.get("source_chunk_ref", "") for e in updated)),
            content=json.dumps(updated, ensure_ascii=False),
            confidence=1.0,
            freshness=1.0,
            model_version="",
            provenance=None,
        )
        self.artifact_store.save(new_artifact)

        gm = sum(1 for r in updated if r.get("coverage_state") == "globally_missing")
        ga = sum(1 for r in updated if r.get("coverage_state") == "globally_answered")

        return {
            "status": "ok",
            "entries_resolved": len(updated),
            "entries_changed": changed,
            "globally_missing_remaining": gm,
            "globally_answered_now": ga,
            "intents_affected": list(affected_intents),
        }
