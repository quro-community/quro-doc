from __future__ import annotations
import json
from datetime import datetime, timezone

from ...config import QuroConfig
from ...artifacts.store import ArtifactStore, Artifact


def _build_what_is_index(
    what_is_artifacts: list[Artifact],
) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for art in what_is_artifacts:
        payload = json.loads(art.content)
        questions = payload.get("questions", [])
        for q in questions:
            qid = q.get("question_id", "")
            if not qid:
                continue
            index.setdefault(qid, []).append({
                "chunk_ref": q.get("source_ref", ""),
                "location_quality": q.get("location_quality", "primary"),
            })
    return index


def _classify_location(chunk_refs: list[str], what_is_index: dict) -> str:
    for ref in chunk_refs:
        quality = what_is_index.get(ref, {}).get("location_quality", "primary")
        if quality in ("primary", "main"):
            return "globally_answered"
    return "discoverability_weak"


def _resolve_single(
    intent_id: str,
    question: str,
    chunk_ref: str,
    what_is_index: dict[str, list[dict]],
) -> dict:
    answered_in = what_is_index.get(intent_id, [])
    if not answered_in:
        state = "globally_missing"
        notes = ""
    elif all(r["chunk_ref"] == chunk_ref for r in answered_in):
        state = "local_missing"
        notes = "same chunk claims it in What-Is but Not-What-Is disagrees"
    else:
        state = _classify_location(
            [r["chunk_ref"] for r in answered_in],
            {r["chunk_ref"]: r for r in answered_in},
        )
        notes = f"answered in: {', '.join(r['chunk_ref'] for r in answered_in)}"

    return {
        "intent_id": intent_id,
        "canonical_question": question,
        "source_chunk_ref": chunk_ref,
        "coverage_state": state,
        "answered_in_chunks": [r["chunk_ref"] for r in answered_in],
        "discoverability_notes": notes,
    }


def resolve(
    not_what_is_artifacts: list[Artifact],
    what_is_artifacts: list[Artifact],
) -> list[dict]:
    what_is_index = _build_what_is_index(what_is_artifacts)
    resolved = []
    for art in not_what_is_artifacts:
        payload = json.loads(art.content)
        chunk_ref = payload["chunk_ref"]
        for entry in payload.get("unanswered", []):
            resolved.append(_resolve_single(
                entry["intent_id"],
                entry["question"],
                chunk_ref,
                what_is_index,
            ))
    return resolved


def run_coverage_resolution(config: QuroConfig | None = None) -> dict:
    config = config or QuroConfig.load()
    if not config.coverage_resolver_enabled:
        return {"status": "disabled"}

    artifact_store = ArtifactStore(config)
    nwi_artifacts = artifact_store.list_by_type("quro.not_what_is.chunk")
    what_is_artifacts = artifact_store.list_by_type("quro.canonical_question.doc")

    resolved = resolve(nwi_artifacts, what_is_artifacts)

    resolved_artifact = Artifact(
        artifact_id=f"cr_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        artifact_type="quro.coverage.resolved",
        schema_version="1.0",
        kind="evidence",
        source_docs=list(set(e["source_chunk_ref"] for e in resolved)),
        content=json.dumps(resolved, ensure_ascii=False),
        confidence=1.0,
        freshness=1.0,
        model_version="",
        provenance=None,
    )
    artifact_store.save(resolved_artifact)

    gm = sum(1 for r in resolved if r["coverage_state"] == "globally_missing")
    lm = sum(1 for r in resolved if r["coverage_state"] == "local_missing")
    ga = sum(1 for r in resolved if r["coverage_state"] == "globally_answered")
    dw = sum(1 for r in resolved if r["coverage_state"] == "discoverability_weak")
    return {
        "status": "ok",
        "entries_resolved": len(resolved),
        "globally_missing": gm,
        "local_missing": lm,
        "globally_answered": ga,
        "discoverability_weak": dw,
    }
