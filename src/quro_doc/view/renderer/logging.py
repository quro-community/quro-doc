from __future__ import annotations
import os
import json
from typing import List, Dict, Any, Optional
from ..candidate import EvidenceCandidate
from .base import QueryContext, ViewTelemetry


def get_log_dir(trace_id: str) -> str:
    base = os.getenv("QURO_LOG_DIR", ".quro_context/logs/quro-docs")
    log_dir = os.path.join(base, trace_id)
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def write_query_json(log_dir: str, query: QueryContext) -> None:
    payload = {
        "query": query.text,
        "params": query.params,
        "trace_id": query.trace_id,
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat().replace("+00:00", "Z"),
    }
    with open(os.path.join(log_dir, "query.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def write_default_view_json(
    log_dir: str, candidates: List[EvidenceCandidate]
) -> None:
    payload = [c.to_dict() for c in candidates]
    with open(os.path.join(log_dir, "default_view.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def write_standard_view_txt(log_dir: str, content: str) -> None:
    with open(os.path.join(log_dir, "standard_view.txt"), "w", encoding="utf-8") as fh:
        fh.write(content)


def write_telemetry_json(log_dir: str, telemetry: ViewTelemetry) -> None:
    with open(os.path.join(log_dir, "telemetry.json"), "w", encoding="utf-8") as fh:
        json.dump(telemetry.to_dict(), fh, ensure_ascii=False, indent=2)


def write_config_snapshot_json(log_dir: str, config: Optional[Dict[str, Any]] = None) -> None:
    if config is None:
        config = {"note": "no config snapshot available"}
    with open(os.path.join(log_dir, "config_snapshot.json"), "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)


def log_standard_view(
    query: QueryContext,
    candidates: List[EvidenceCandidate],
    content: str,
    telemetry: ViewTelemetry,
    config: Optional[Dict[str, Any]] = None,
) -> None:
    log_dir = get_log_dir(query.trace_id)
    write_query_json(log_dir, query)
    write_config_snapshot_json(log_dir, config)
    write_default_view_json(log_dir, candidates)
    write_standard_view_txt(log_dir, content)
    write_telemetry_json(log_dir, telemetry)
