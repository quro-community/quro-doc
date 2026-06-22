from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Dict, Optional
from datetime import datetime, timezone

from ..trace.model import Provenance


@dataclass
class EvidenceCandidate:
    candidate_id: str
    source_type: str
    content: str
    metadata: Dict
    retrieval_signal: Dict[str, float] = field(default_factory=dict)
    runtime_cost: Dict[str, int | float] = field(default_factory=lambda: {"token_cost": 0, "latency_cost": 0, "redundancy_cost": 0})
    confidence: float = 0.0
    provenance: List[Provenance] = field(default_factory=list)
    artifact_feature: Dict = field(default_factory=dict)

    @staticmethod
    def from_chunk(doc_id: str, chunk_id: str, content: str, source_type: str = "raw",
                   tags: Optional[List[str]] = None, created_at: Optional[str] = None) -> "EvidenceCandidate":
        candidate_id = f"{doc_id}::{chunk_id}::cand" if chunk_id else f"{doc_id}::cand"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return EvidenceCandidate(
            candidate_id=candidate_id,
            source_type=source_type,
            content=content,
            metadata={
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "tags": tags or [],
                "created_at": created_at or "",
            },
            retrieval_signal={"rerank_relevance": 0.0},
            runtime_cost={"token_cost": len(content.split()), "latency_cost": 0, "redundancy_cost": 0},
            provenance=[Provenance(
                source_doc_id=doc_id,
                pipeline_stage="extraction",
                timestamp=now,
                transform="chunk",
            )],
        )

    def to_dict(self) -> Dict:
        return {
            "candidate_id": self.candidate_id,
            "source_type": self.source_type,
            "content": self.content,
            "metadata": self.metadata,
            "retrieval_signal": self.retrieval_signal,
            "runtime_cost": self.runtime_cost,
            "confidence": self.confidence,
            "provenance": [{"source_doc_id": p.source_doc_id, "pipeline_stage": p.pipeline_stage, "timestamp": p.timestamp, "transform": p.transform} for p in self.provenance],
            "artifact_feature": self.artifact_feature,
        }
