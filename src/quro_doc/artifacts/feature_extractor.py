from __future__ import annotations
from dataclasses import dataclass
from typing import List

from ..view.candidate import EvidenceCandidate
from .store import Artifact


@dataclass
class EvidenceFeature:
    semantic_match: float
    canonical_alignment: float
    qa_reuse_probability: float
    summary_density: float
    contradiction_risk: float
    token_cost: int


class ArtifactFeatureExtractor:
    def extract(
        self,
        candidates: List[EvidenceCandidate],
        artifacts: List[Artifact],
    ) -> List[EvidenceFeature]:
        artifacts_by_source: dict[str, list[Artifact]] = {}
        for a in artifacts:
            for sd in a.source_docs:
                artifacts_by_source.setdefault(sd, []).append(a)

        features = []
        for candidate in candidates:
            doc_id = candidate.metadata.get("doc_id", "")
            matched = artifacts_by_source.get(doc_id, [])
            if matched:
                best = max(matched, key=lambda a: a.confidence)
                features.append(EvidenceFeature(
                    semantic_match=best.confidence,
                    canonical_alignment=best.freshness,
                    qa_reuse_probability=best.confidence * 0.8,
                    summary_density=0.5,
                    contradiction_risk=1.0 - best.confidence,
                    token_cost=len(best.content.split()),
                ))
            else:
                features.append(EvidenceFeature(
                    semantic_match=0.0,
                    canonical_alignment=0.0,
                    qa_reuse_probability=0.0,
                    summary_density=0.0,
                    contradiction_risk=0.0,
                    token_cost=len(candidate.content.split()),
                ))
        return features
