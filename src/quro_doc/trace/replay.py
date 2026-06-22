from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

from .model import Trace, FinalAssembly


class ReplayMode(Enum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    POLICY_ONLY = "policy_only"


@dataclass
class ReplayResult:
    trace_id: str
    mode: ReplayMode
    assembly: FinalAssembly
    match: bool
    replay_telemetry: dict = field(default_factory=dict)


class ReplayEngine:
    def replay(self, trace: Trace, mode: ReplayMode) -> ReplayResult:
        if mode == ReplayMode.EXACT:
            return self._replay_exact(trace)
        elif mode == ReplayMode.APPROXIMATE:
            return self._replay_approximate(trace)
        elif mode == ReplayMode.POLICY_ONLY:
            return self._replay_policy_only(trace)
        else:
            raise ValueError(f"Unknown replay mode: {mode}")

    def _replay_exact(self, trace: Trace) -> ReplayResult:
        original = trace.assembly.rendered_context
        assembly = FinalAssembly(
            selected_candidates=[c.candidate_id for c in (trace.evidence_flow.candidates_after_rerank or trace.evidence_flow.candidates_before_rerank)],
            rendered_context=original,
            token_usage=trace.assembly.token_usage,
        )
        return ReplayResult(
            trace_id=trace.trace_id,
            mode=ReplayMode.EXACT,
            assembly=assembly,
            match=True,
            replay_telemetry={"mode": "exact", "candidates_frozen": len(assembly.selected_candidates)},
        )

    def _replay_approximate(self, trace: Trace) -> ReplayResult:
        from ..pipelines.query_pipeline import _legacy_search_with_evidence, enrich_legacy_results
        from ..view.renderer.standard import get_renderer
        from ..view.renderer.base import QueryContext

        top_k = trace.policy.pruner_params.get("top_k", 10)
        results, _ = _legacy_search_with_evidence(
            trace.query.text,
            top_k,
            trace.query.params.get("tags", []),
        )
        candidates = enrich_legacy_results(results)

        qctx = QueryContext(
            text=trace.query.text,
            trace_id=trace.trace_id,
            params=trace.query.params,
        )
        renderer = get_renderer("standard-view")
        if renderer is None:
            raise RuntimeError("standard-view renderer not available")
        rendered = renderer.render(candidates, qctx)

        new_content = rendered.content
        match = (new_content == trace.assembly.rendered_context)

        assembly = FinalAssembly(
            selected_candidates=[c.candidate_id for c in candidates],
            rendered_context=new_content,
            token_usage=len(new_content.split()),
        )
        return ReplayResult(
            trace_id=trace.trace_id,
            mode=ReplayMode.APPROXIMATE,
            assembly=assembly,
            match=match,
            replay_telemetry={
                "mode": "approximate",
                "match": match,
                "candidates_retrieved": len(candidates),
            },
        )

    def _replay_policy_only(self, trace: Trace) -> ReplayResult:
        from ..pipelines.query_pipeline import _legacy_search_with_evidence, enrich_legacy_results
        from ..view.renderer.standard import get_renderer
        from ..view.renderer.base import QueryContext

        top_k = trace.policy.pruner_params.get("top_k", 10)
        results, _ = _legacy_search_with_evidence(
            trace.query.text,
            top_k,
            trace.query.params.get("tags", []),
        )
        candidates = enrich_legacy_results(results)

        qctx = QueryContext(
            text=trace.query.text,
            trace_id=trace.trace_id,
            params=trace.query.params,
        )
        renderer = get_renderer("standard-view")
        if renderer is None:
            raise RuntimeError("standard-view renderer not available")
        rendered = renderer.render(candidates, qctx)

        assembly = FinalAssembly(
            selected_candidates=[c.candidate_id for c in candidates],
            rendered_context=rendered.content,
            token_usage=len(rendered.content.split()),
        )
        return ReplayResult(
            trace_id=trace.trace_id,
            mode=ReplayMode.POLICY_ONLY,
            assembly=assembly,
            match=False,
            replay_telemetry={
                "mode": "policy_only",
                "candidates_retrieved": len(candidates),
            },
        )
