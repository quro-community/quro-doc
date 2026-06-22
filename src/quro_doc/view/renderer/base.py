from typing import Protocol, List, Dict, Any
from dataclasses import dataclass, field
from ..candidate import EvidenceCandidate


@dataclass
class QueryContext:
    text: str
    trace_id: str
    params: dict


@dataclass
class ViewTelemetry:
    trace_id: str
    view_name: str
    result_status: str = "ok"
    default_view_latency_ms: float = 0.0
    standard_view_latency_ms: float = 0.0
    candidates_considered: int = 0
    candidates_selected: int = 0
    sections_planned: int = 0
    sections_with_evidence: int = 0
    estimated_tokens: int = 0
    token_budget: int = 0
    token_usage: int = 0
    sections: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    evidence_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "view_name": self.view_name,
            "result_status": self.result_status,
            "default_view_latency_ms": self.default_view_latency_ms,
            "standard_view_latency_ms": self.standard_view_latency_ms,
            "candidates_considered": self.candidates_considered,
            "candidates_selected": self.candidates_selected,
            "sections_planned": self.sections_planned,
            "sections_with_evidence": self.sections_with_evidence,
            "estimated_tokens": self.estimated_tokens,
            "token_budget": self.token_budget,
            "token_usage": self.token_usage,
            "sections": self.sections,
            "evidence_warnings": self.evidence_warnings,
        }


@dataclass
class RenderedView:
    content: str
    format: str
    telemetry: ViewTelemetry
    metadata: Dict[str, Any]

    def to_response(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "format": self.format,
            "view": self.telemetry.view_name,
            "trace_id": self.telemetry.trace_id,
            "telemetry": self.telemetry.to_dict(),
        }


class ViewRenderer(Protocol):
    name: str

    def render(
        self,
        candidates: List[EvidenceCandidate],
        query: QueryContext,
    ) -> RenderedView:
        ...
