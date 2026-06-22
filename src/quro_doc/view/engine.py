from __future__ import annotations
from typing import Dict, Any, List, Optional

from .candidate import EvidenceCandidate


class ViewLayerOrchestrator:
    def render(
        self,
        view_name: str,
        candidates: List[EvidenceCandidate],
        query_text: str,
        trace_id: str,
        query_params: Optional[Dict] = None,
        config=None,
    ) -> Dict[str, Any]:
        from .renderer.base import QueryContext
        from .renderer.standard import get_renderer
        from .renderer.default import DefaultViewRenderer

        qctx = QueryContext(
            text=query_text,
            trace_id=trace_id,
            params=query_params or {},
        )

        config_snapshot = config.to_dict() if config else None

        if view_name in ("standard", "standard-view"):
            standard_enabled = True
            if config:
                standard_enabled = config.standard_view_enabled
            else:
                import os
                standard_enabled = os.getenv("STANDARD_VIEW_ENABLED", "true").lower() == "true"
            if not standard_enabled:
                return {"error": "Standard View disabled via STANDARD_VIEW_ENABLED=false"}
            renderer = get_renderer("standard-view")
            if renderer is None:
                return {"error": "Standard View renderer not available"}
            rendered = renderer.render(candidates, qctx, config_snapshot=config_snapshot)
            return rendered.to_response()

        # Default view (backward compatible)
        renderer = DefaultViewRenderer()
        rendered = renderer.render(candidates, qctx)
        return {
            "content": rendered.content,
            "format": rendered.format,
            "view": "default-view",
            "trace_id": trace_id,
            "telemetry": rendered.telemetry.to_dict(),
            "candidates": [c.to_dict() for c in candidates],
        }
