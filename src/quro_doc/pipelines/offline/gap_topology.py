from __future__ import annotations
import json
from datetime import datetime, timezone

from ...config import QuroConfig
from ...artifacts.store import ArtifactStore, Artifact


_CATEGORY_PATTERNS: dict[str, list[str]] = {
    "lifecycle_documentation": [
        "startup", "shutdown", "lifecycle", "init", "cleanup", "teardown",
    ],
    "orchestration_wiring": [
        "pipeline", "orchestrat", "wiring", "assembly", "integration",
    ],
    "ownership_responsibility": [
        "owner", "responsible", "maintainer", "accountable",
    ],
    "error_handling_edge_cases": [
        "error", "exception", "edge case", "failure", "fallback",
    ],
    "teardown_cleanup": ["teardown", "cleanup", "gc", "garbage", "release"],
    "async_ordering": ["async", "ordering", "concurrency", "race", "deadlock"],
    "cache_invalidation": ["cache", "invalidat", "stale", "refresh", "ttl", "expir"],
}


def _infer_category(intent_id: str) -> str:
    lower = intent_id.lower()
    for category, patterns in _CATEGORY_PATTERNS.items():
        for p in patterns:
            if p in lower:
                return category
    return "other"


def _load_latest_resolved(artifact_store: ArtifactStore) -> list[dict]:
    artifacts = artifact_store.list_by_type("quro.coverage.resolved")
    if not artifacts:
        return []
    latest = max(
        artifacts,
        key=lambda a: a.created_at or datetime.min.replace(tzinfo=timezone.utc),
    )
    return json.loads(latest.content)


def analyze(resolved_entries: list[dict]) -> dict:
    globally_missing = [
        r for r in resolved_entries if r["coverage_state"] == "globally_missing"
    ]
    discoverability_weak = [
        r for r in resolved_entries
        if r["coverage_state"] == "discoverability_weak"
    ]

    categories: dict[str, dict] = {}
    for entry in globally_missing:
        cat = _infer_category(entry["intent_id"])
        if cat not in categories:
            categories[cat] = {"category": cat, "count": 0, "example_intents": []}
        categories[cat]["count"] += 1
        if len(categories[cat]["example_intents"]) < 3:
            categories[cat]["example_intents"].append(entry["intent_id"])

    weak_details = []
    for entry in discoverability_weak:
        weak_details.append({
            "intent_id": entry["intent_id"],
            "located_in": entry.get("answered_in_chunks", ["unknown"])[0],
            "note": entry.get("discoverability_notes", ""),
        })

    return {
        "project": "quro-doc",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "globally_missing_categories": sorted(
            categories.values(), key=lambda c: c["count"], reverse=True
        ),
        "discoverability_weak_intents": weak_details,
    }


def run_gap_topology(config: QuroConfig | None = None) -> dict:
    config = config or QuroConfig.load()
    if not config.gap_topology_enabled:
        return {"status": "disabled"}

    artifact_store = ArtifactStore(config)
    resolved_entries = _load_latest_resolved(artifact_store)
    if not resolved_entries:
        return {
            "status": "ok",
            "globally_missing_categories": [],
            "discoverability_weak_intents": [],
        }

    report = analyze(resolved_entries)

    report_artifact = Artifact(
        artifact_id=f"gt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        artifact_type="quro.gap.topology",
        schema_version="1.0",
        kind="evidence",
        source_docs=[],
        content=json.dumps(report, ensure_ascii=False),
        confidence=1.0,
        freshness=1.0,
        model_version="",
        provenance=None,
    )
    artifact_store.save(report_artifact)

    return {
        "status": "ok",
        "globally_missing_categories": report["globally_missing_categories"],
        "globally_missing_total": len(report["globally_missing_categories"]),
        "discoverability_weak_intents": report["discoverability_weak_intents"],
        "discoverability_weak_total": len(report["discoverability_weak_intents"]),
    }
