from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from datetime import datetime, timezone

if TYPE_CHECKING:
    from ..trace.model import Trace


@dataclass
class ArtifactProvenance:
    source_refs: list[str] = field(default_factory=list)
    extractor: str = ""
    model_version: str = ""
    pipeline_run_id: str = ""
    input_snapshot_id: str = ""
    trace_window_id: str | None = None


def _generate_pipeline_run_id() -> str:
    return f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{id(datetime)}"


class ProvenanceTracker:
    def record(
        self,
        *,
        source_refs: list[str],
        extractor: str,
        model_version: str,
        pipeline_run_id: str | None = None,
        input_snapshot_id: str = "",
        trace_window_id: str | None = None,
    ) -> ArtifactProvenance:
        return ArtifactProvenance(
            source_refs=source_refs,
            extractor=extractor,
            model_version=model_version,
            pipeline_run_id=pipeline_run_id or _generate_pipeline_run_id(),
            input_snapshot_id=input_snapshot_id,
            trace_window_id=trace_window_id,
        )

    def from_trace(
        self,
        trace: Trace,
        doc_ids: list[str],
        extractor: str,
    ) -> ArtifactProvenance:
        model_version = trace.versions.artifact_pipeline_version or trace.versions.embedding_model
        return ArtifactProvenance(
            source_refs=doc_ids,
            extractor=extractor,
            model_version=model_version,
            pipeline_run_id=_generate_pipeline_run_id(),
            input_snapshot_id=trace.versions.scoring_engine_version,
            trace_window_id=trace.trace_id,
        )
