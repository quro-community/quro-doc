from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from ..candidate import EvidenceCandidate
from .base import ViewTelemetry


STANDARD_SECTIONS = [
    "Goal",
    "Summary",
    "Architecture",
    "Dir Structure",
    "DataFlow",
    "Files",
]


@dataclass
class Section:
    title: str
    summary: str
    evidence: List[EvidenceCandidate] = field(default_factory=list)
    evidence_warnings: List[str] = field(default_factory=list)


@dataclass
class StandardView:
    sections: List[Section]
    metadata: ViewTelemetry
    query: str

    def render_txt(self) -> str:
        lines = []
        lines.append("[Metadata]")
        lines.append(f"  trace-id: {self.metadata.trace_id}")
        lines.append("")
        for section in self.sections:
            lines.append(f"[{section.title}]")
            if section.summary:
                lines.append(section.summary)
            for ev in section.evidence:
                doc_id = ev.metadata.get("doc_id", "")
                chunk_id = ev.metadata.get("chunk_id", "")
                body = ev.content.strip()
                if doc_id:
                    lines.append(f"  \u2022 {doc_id}: {body}")
                else:
                    lines.append(f"  \u2022 {body}")
            lines.append("")
        return "\n".join(lines).strip()
