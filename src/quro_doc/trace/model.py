from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Dict, Optional
from datetime import datetime

if TYPE_CHECKING:
    from ..view.renderer.base import QueryContext



@dataclass
class Provenance:
    source_doc_id: str
    pipeline_stage: str
    timestamp: str
    transform: str | None = None


@dataclass
class RuntimePolicy:
    scorer_weights: Dict[str, float]
    pruner_strategy: str
    pruner_params: Dict
    token_budget: int
    diversity_lambda: float | None = None
    artifact_feature_weight: float = 0.0


@dataclass
class RuntimeVersions:
    embedding_model: str
    reranker_model: str
    prompt_template_version: str
    artifact_pipeline_version: str
    scoring_engine_version: str


@dataclass
class CandidateSnapshot:
    candidate_id: str
    content_ref: str
    source_type: str
    retrieval_signal: Dict
    artifact_feature: Dict
    runtime_cost: Dict
    provenance: List[Provenance]


@dataclass
class EvidenceFlow:
    candidates_before_rerank: List[CandidateSnapshot]
    candidates_after_rerank: List[CandidateSnapshot] | None = None
    candidates_after_prune: List[CandidateSnapshot] | None = None


@dataclass
class FinalAssembly:
    selected_candidates: List[str]
    rendered_context: str
    token_usage: int


@dataclass
class TraceTelemetry:
    retrieval_latency_ms: float
    rerank_latency_ms: float | None = None
    prune_latency_ms: float | None = None
    candidate_count_before_rerank: int = 0
    candidate_count_after_prune: int = 0
    truncated: bool = False
    truncation_threshold: int | None = None


@dataclass
class Trace:
    trace_id: str
    timestamp: datetime
    query: "QueryContext"
    policy: RuntimePolicy
    versions: RuntimeVersions
    evidence_flow: EvidenceFlow
    assembly: FinalAssembly
    telemetry: TraceTelemetry
    feature_flags: Dict[str, bool]



