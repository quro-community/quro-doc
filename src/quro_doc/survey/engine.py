from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any

from ..config import QuroConfig
from ..artifacts.store import ArtifactStore


class QaQualitySurvey:
    def __init__(self, config: QuroConfig | None = None):
        self.config = config or QuroConfig.load()
        self.artifact_store = ArtifactStore(self.config)

    def get_summary(self, survey_type: str = "globally_missing") -> dict[str, Any]:
        gap_artifacts = self.artifact_store.list_by_type("quro.gap.topology")
        if not gap_artifacts:
            return {"status": "no_data", "message": "Run gap topology pipeline first"}

        latest_gap = max(
            gap_artifacts,
            key=lambda a: a.created_at or datetime.min.replace(tzinfo=timezone.utc),
        )
        gap_data = json.loads(latest_gap.content)

        resolved_artifacts = self.artifact_store.list_by_type("quro.coverage.resolved")
        resolved_entries = []
        if resolved_artifacts:
            latest_resolved = max(
                resolved_artifacts,
                key=lambda a: a.created_at or datetime.min.replace(tzinfo=timezone.utc),
            )
            resolved_entries = json.loads(latest_resolved.content)

        globally_missing_categories = gap_data.get("globally_missing_categories", [])
        discoverability_weak_intents = gap_data.get("discoverability_weak_intents", [])

        total_globally_missing = sum(c["count"] for c in globally_missing_categories)
        discoverability_weak_count = len(discoverability_weak_intents)

        globally_missing_intent_ids = set()
        for cat in globally_missing_categories:
            for ex in cat.get("example_intents", []):
                globally_missing_intent_ids.add(ex)

        matched_entries = [
            e for e in resolved_entries
            if e["intent_id"] in globally_missing_intent_ids
        ]

        entries = []
        for entry in matched_entries:
            cat = self._find_category(globally_missing_categories, entry["intent_id"])
            entries.append({
                "intent_id": entry["intent_id"],
                "canonical_question": entry.get("canonical_question", ""),
                "source_chunk_ref": entry.get("source_chunk_ref", ""),
                "coverage_state": entry.get("coverage_state", "globally_missing"),
                "discoverability_notes": entry.get("discoverability_notes", ""),
                "topology_category": cat,
            })

        return {
            "survey_type": survey_type,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "artifact_ref": latest_gap.artifact_id,
            "summary": {
                "total_globally_missing": total_globally_missing,
                "categories": globally_missing_categories,
                "discoverability_weak": discoverability_weak_count,
            },
            "entries": entries,
        }

    @staticmethod
    def _find_category(categories: list[dict], intent_id: str) -> str:
        for cat in categories:
            if intent_id in cat.get("example_intents", []):
                return cat["category"]
        return "other"
