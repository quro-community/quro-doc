from __future__ import annotations
import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dataclasses import asdict

from .model import Trace
from ..config import QuroConfig


def _serialize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat().replace("+00:00", "Z")
    if hasattr(obj, "_asdict"):
        return obj._asdict()
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    return obj


def _strip_meta(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ("schema_version", "trace_id", "timestamp")}


def _deserialize_trace(data: dict) -> Trace:
    from .model import (
        RuntimePolicy, RuntimeVersions, EvidenceFlow,
        CandidateSnapshot, Provenance, FinalAssembly, TraceTelemetry,
    )
    from ..view.renderer.base import QueryContext

    q = data["query"]
    query = QueryContext(text=q["text"], trace_id=q["trace_id"], params=q["params"])

    p = _strip_meta(data["policy"])
    policy = RuntimePolicy(**p)

    v = _strip_meta(data["versions"])
    versions = RuntimeVersions(**v)

    ef = _strip_meta(data["evidence_flow"])
    evidence_flow = EvidenceFlow(
        candidates_before_rerank=[_deserialize_candidate(c) for c in ef["candidates_before_rerank"]],
        candidates_after_rerank=[_deserialize_candidate(c) for c in (ef.get("candidates_after_rerank") or [])] if ef.get("candidates_after_rerank") else None,
        candidates_after_prune=[_deserialize_candidate(c) for c in (ef.get("candidates_after_prune") or [])] if ef.get("candidates_after_prune") else None,
    )

    a = data["assembly"]
    assembly = FinalAssembly(**a)

    t = _strip_meta(data["telemetry"])
    telemetry = TraceTelemetry(**t)

    return Trace(
        trace_id=data["trace_id"],
        timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
        query=query,
        policy=policy,
        versions=versions,
        evidence_flow=evidence_flow,
        assembly=assembly,
        telemetry=telemetry,
        feature_flags=data.get("feature_flags", {}),
    )


def _deserialize_candidate(c: dict) -> CandidateSnapshot:
    from .model import CandidateSnapshot, Provenance
    return CandidateSnapshot(
        candidate_id=c["candidate_id"],
        content_ref=c["content_ref"],
        source_type=c["source_type"],
        retrieval_signal=c.get("retrieval_signal", {}),
        artifact_feature=c.get("artifact_feature", {}),
        runtime_cost=c.get("runtime_cost", {}),
        provenance=[Provenance(**p) for p in c.get("provenance", [])],
    )


def _write_json(path: Path, obj) -> None:
    path.write_text(
        json.dumps(_serialize(obj), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class TraceStore:
    def __init__(self, config: Optional[QuroConfig] = None):
        self.config = config or QuroConfig.load()
        self.root = Path(self.config.storage_root)

    def _trace_dir(self, trace_id: str) -> Path:
        return self.root / "logs" / "quro-docs" / trace_id

    def save(self, trace: Trace) -> str:
        for attempt in range(3):
            try:
                tdir = self._trace_dir(trace.trace_id)
                tdir.mkdir(parents=True, exist_ok=True)

                schema_meta = {
                    "schema_version": "1.0",
                    "trace_id": trace.trace_id,
                    "timestamp": trace.timestamp.isoformat().replace("+00:00", "Z"),
                }

                q = _serialize(trace.query)
                q.update(schema_meta)
                _write_json(tdir / "query.json", q)

                p = _serialize(trace.policy)
                p.update(schema_meta)
                _write_json(tdir / "policy.json", p)

                v = _serialize(trace.versions)
                v.update(schema_meta)
                _write_json(tdir / "versions.json", v)

                ef = _serialize(trace.evidence_flow)
                ef.update(schema_meta)
                _write_json(tdir / "evidence_flow.json", ef)

                assembly_path = tdir / "assembly.txt"
                assembly_path.write_text(trace.assembly.rendered_context, encoding="utf-8")

                tlm = _serialize(trace.telemetry)
                tlm.update(schema_meta)
                _write_json(tdir / "telemetry.json", tlm)

                ff = _serialize(trace.feature_flags)
                ff.update(schema_meta)
                _write_json(tdir / "feature_flags.json", ff)

                return trace.trace_id
            except Exception:
                if attempt < 2:
                    time.sleep(0.1 * (2 ** attempt))
                else:
                    pass
        return trace.trace_id

    def load(self, trace_id: str) -> Trace:
        tdir = self._trace_dir(trace_id)
        if not tdir.exists():
            raise FileNotFoundError(f"Trace {trace_id} not found")

        data = {
            "trace_id": trace_id,
            "timestamp": _read_json(tdir / "query.json")["timestamp"],
            "query": _read_json(tdir / "query.json"),
            "policy": _read_json(tdir / "policy.json"),
            "versions": _read_json(tdir / "versions.json"),
            "evidence_flow": _read_json(tdir / "evidence_flow.json"),
            "assembly": {
                "selected_candidates": [],
                "rendered_context": (tdir / "assembly.txt").read_text(encoding="utf-8"),
                "token_usage": 0,
            },
            "telemetry": _read_json(tdir / "telemetry.json"),
            "feature_flags": _read_json(tdir / "feature_flags.json"),
        }
        return _deserialize_trace(data)

    def list(self, since: datetime = None, limit: int = 100) -> list[str]:
        base = self.root / "logs" / "quro-docs"
        if not base.exists():
            return []
        trace_ids = []
        for entry in sorted(base.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            qfile = entry / "query.json"
            if not qfile.exists():
                continue
            if since is not None:
                try:
                    meta = json.loads(qfile.read_text(encoding="utf-8"))
                    ts = datetime.fromisoformat(meta["timestamp"].replace("Z", "+00:00"))
                    if ts < since:
                        continue
                except Exception:
                    pass
            trace_ids.append(entry.name)
            if len(trace_ids) >= limit:
                break
        return trace_ids
