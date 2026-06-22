from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timezone

from ..artifacts.feature_extractor import EvidenceFeature


@dataclass
class PerCandidateDecision:
    candidate_id: str
    rank: int
    score: float
    action: str
    reason: str


@dataclass
class RankingDecision:
    policy_id: str
    policy_version: str
    applied_at: str
    decisions: List[PerCandidateDecision]

    def to_dict(self) -> dict:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "applied_at": self.applied_at,
            "decisions": [
                {"candidate_id": d.candidate_id, "rank": d.rank, "score": d.score, "action": d.action, "reason": d.reason}
                for d in self.decisions
            ],
        }


DEFAULT_WEIGHTS = {
    "semantic_match": 1.0,
    "canonical_alignment": 0.5,
    "qa_reuse_probability": 0.3,
    "summary_density": 0.2,
    "contradiction_risk": -0.5,
}


class RankingPolicy:
    def __init__(
        self,
        weights: dict[str, float] | None = None,
        policy_id: str | None = None,
        policy_version: str | None = None,
    ):
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        self.policy_id = policy_id or "default_ranking_policy"
        self.policy_version = policy_version or "1.0.0"

    def evaluate(
        self,
        features: List[EvidenceFeature],
        candidate_ids: Optional[List[str]] = None,
    ) -> RankingDecision:
        scored = []
        for i, f in enumerate(features):
            vals = {
                "semantic_match": f.semantic_match,
                "canonical_alignment": f.canonical_alignment,
                "qa_reuse_probability": f.qa_reuse_probability,
                "summary_density": f.summary_density,
                "contradiction_risk": f.contradiction_risk,
            }
            utility = 0.0
            for key, val in vals.items():
                utility += val * self.weights.get(key, 0.0)
            cid = candidate_ids[i] if candidate_ids and i < len(candidate_ids) else str(i)
            scored.append((cid, utility))

        scored.sort(key=lambda x: x[1], reverse=True)

        decisions = []
        for rank, (cid, utility) in enumerate(scored):
            decisions.append(PerCandidateDecision(
                candidate_id=cid,
                rank=rank,
                score=round(utility, 6),
                action="include" if utility >= 0 else "exclude",
                reason=f"utility_{round(utility, 4)}",
            ))

        return RankingDecision(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            applied_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            decisions=decisions,
        )
