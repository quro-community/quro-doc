from __future__ import annotations
import time
from typing import List, Optional
from ..candidate import EvidenceCandidate
from .base import (
    ViewRenderer,
    QueryContext,
    RenderedView,
    ViewTelemetry,
)
from .section_planner import SectionPlanner, StandardViewConfig
from .standard_ast import StandardView
from ...trace.store import TraceStore

RENDERER_REGISTRY: dict = {}


def register_renderer(name: str):
    def decorator(cls):
        RENDERER_REGISTRY[name] = cls
        return cls
    return decorator


def get_renderer(name: str) -> Optional[ViewRenderer]:
    cls = RENDERER_REGISTRY.get(name)
    if cls is None:
        return None
    return cls()


@register_renderer("standard-view")
class StandardViewRenderer:
    name = "standard-view"

    def __init__(self, config: Optional[StandardViewConfig] = None):
        self.config = config or StandardViewConfig.from_env()
        self.planner = SectionPlanner(self.config)

    def render(
        self,
        candidates: List[EvidenceCandidate],
        query: QueryContext,
        config_snapshot: Optional[dict] = None,
    ) -> RenderedView:
        start = time.time()

        sections = self.planner.plan(candidates, query)

        evidence_warnings = []
        for s in sections:
            if s.evidence_warnings:
                evidence_warnings.extend(s.evidence_warnings)

        telemetry = ViewTelemetry(
            trace_id=query.trace_id,
            view_name=self.name,
            candidates_considered=len(candidates),
            candidates_selected=sum(len(s.evidence) for s in sections),
            sections_planned=len(sections),
            sections_with_evidence=len([s for s in sections if s.evidence]),
            token_budget=self.config.token_budget,
            evidence_warnings=evidence_warnings,
        )

        ast = StandardView(
            sections=sections,
            metadata=telemetry,
            query=query.text,
        )

        content = ast.render_txt()

        telemetry.estimated_tokens = len(content.split())
        telemetry.token_usage = telemetry.estimated_tokens
        telemetry.standard_view_latency_ms = round((time.time() - start) * 1000, 2)

        telemetry.sections = {}
        for s in sections:
            sec_tokens = sum(e.runtime_cost.get("token_cost", 0) for e in s.evidence)
            telemetry.sections[s.title] = {
                "candidates": len(s.evidence),
                "tokens": sec_tokens,
            }

        return RenderedView(
            content=content,
            format="txt",
            telemetry=telemetry,
            metadata={"sections": [s.title for s in sections]},
        )
