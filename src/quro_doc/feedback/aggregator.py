from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any

from .store import FeedbackStore
from ..config import QuroConfig
from ..artifacts.store import ArtifactStore, Artifact


class FeedbackReviewAggregator:
    def __init__(self, config: QuroConfig | None = None):
        self.config = config or QuroConfig.load()
        self.feedback_store = FeedbackStore()
        self.artifact_store = ArtifactStore(self.config)

    def aggregate(self, intent_id: str | None = None) -> dict[str, Any]:
        all_feedback = self.feedback_store.list_all_raw()
        if not all_feedback:
            return {"status": "ok", "total_feedback": 0, "reviews": []}

        if intent_id:
            filtered = [f for f in all_feedback if f.get("target", {}).get("intent_id") == intent_id]
        else:
            filtered = all_feedback

        if not filtered:
            return {"status": "ok", "total_feedback": 0, "reviews": []}

        grouped: dict[str, list[dict]] = {}
        for fb in filtered:
            iid = fb.get("target", {}).get("intent_id", "unknown")
            grouped.setdefault(iid, []).append(fb)

        reviews: list[dict[str, Any]] = []
        for iid, entries in grouped.items():
            total = len(entries)
            low_quality = sum(
                1 for e in entries
                if any(e.get("quality_flags", {}).get(k, False)
                       for k in ("is_hallucinated", "is_not_grounded", "is_vague", "is_ambiguous", "has_wrong_intent"))
            )
            low_quality_ratio = round(low_quality / total, 2) if total else 0.0

            flag_dist: dict[str, int] = {}
            for e in entries:
                flags = e.get("quality_flags", {})
                for k, v in flags.items():
                    if v and isinstance(v, bool):
                        flag_dist[k] = flag_dist.get(k, 0) + 1

            question_variants: dict[str, list[float]] = {}
            for e in entries:
                qt = e.get("qa_pair", {}).get("query", "")
                if qt:
                    question_variants.setdefault(qt, []).append(
                        1.0 - low_quality_ratio
                    )

            variants = [
                {
                    "question_text": q,
                    "frequency": len(scores),
                    "avg_quality": round(sum(scores) / len(scores), 2),
                }
                for q, scores in sorted(question_variants.items(), key=lambda x: -len(x[1]))
            ]

            ratio = low_quality_ratio
            freq = total
            if ratio >= 0.6 and freq >= 2:
                priority = "high"
            elif ratio >= 0.3:
                priority = "medium"
            else:
                priority = "low"

            reviews.append({
                "intent_id": iid,
                "total_feedback": total,
                "low_quality_ratio": low_quality_ratio,
                "flag_distribution": flag_dist,
                "question_variants": variants,
                "investigation_priority": priority,
            })

        reviews.sort(key=lambda r: r.get("total_feedback", 0), reverse=True)  # type: ignore[return-value]
        return {"status": "ok", "total_feedback": len(filtered), "reviews": reviews}

    def produce_review_artifact(self) -> str | None:
        result = self.aggregate()
        if not result.get("reviews"):
            return None

        artifact = Artifact(
            artifact_id=f"fr_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            artifact_type="quro.feedback.review",
            schema_version="1.0",
            kind="evidence",
            source_docs=[],
            content=json.dumps(result, ensure_ascii=False),
            confidence=1.0,
            freshness=1.0,
            model_version="",
            provenance=None,
        )
        return self.artifact_store.save(artifact)
