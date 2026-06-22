from __future__ import annotations
from collections import Counter
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional

from ...trace.store import TraceStore
from ...trace.model import Provenance
from ...config import QuroConfig


@dataclass
class HotDocResult:
    doc_id: str
    frequency: int
    trace_ids: list[str]


class HotDocScanner:
    def __init__(self, config: Optional[QuroConfig] = None):
        self.config = config or QuroConfig.load()
        self.trace_store = TraceStore(self.config)

    def scan(self, since: Optional[datetime] = None) -> list[HotDocResult]:
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=24)

        trace_ids = self.trace_store.list(since=since)
        freq: Counter = Counter()
        trace_map: dict[str, list[str]] = {}

        for tid in trace_ids:
            try:
                trace = self.trace_store.load(tid)
            except Exception:
                continue
            doc_ids = set()
            for c in trace.evidence_flow.candidates_before_rerank:
                for p in c.provenance:
                    doc_ids.add(p.source_doc_id)
            for d in doc_ids:
                freq[d] += 1
                if d not in trace_map:
                    trace_map[d] = []
                trace_map[d].append(tid)

        results = []
        for doc_id, count in freq.most_common():
            results.append(HotDocResult(
                doc_id=doc_id,
                frequency=count,
                trace_ids=trace_map.get(doc_id, []),
            ))
        return results
