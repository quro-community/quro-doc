from __future__ import annotations
from typing import List
from ..candidate import EvidenceCandidate
from .base import ViewRenderer, QueryContext, RenderedView, ViewTelemetry


class DefaultViewRenderer:
    name = "default-view"

    def render(
        self,
        candidates: List[EvidenceCandidate],
        query: QueryContext,
    ) -> RenderedView:
        candidates_dicts = [c.to_dict() for c in candidates]
        telemetry = ViewTelemetry(
            trace_id=query.trace_id,
            view_name=self.name,
            candidates_considered=len(candidates),
            candidates_selected=len(candidates),
        )
        import json
        content = json.dumps(candidates_dicts, ensure_ascii=False, indent=2)
        return RenderedView(
            content=content,
            format="json",
            telemetry=telemetry,
            metadata={"candidate_count": len(candidates)},
        )
