from __future__ import annotations
import os
import re
import json
import hashlib
from datetime import datetime, timezone

from ...config import QuroConfig
from ...artifacts.store import ArtifactStore, Artifact
from ...artifacts.provenance import ProvenanceTracker
from ...prompts import render


DEFAULT_MAX_ENTRIES = 20
DEFAULT_EXTRACTOR_VERSION = "1.0.0"


def _validate_unanswered(entries: list[dict]) -> list[dict]:
    validated = []
    for e in entries:
        intent_id = e.get("intent_id", "").strip()
        question = e.get("question", "").strip()
        if not intent_id or not question:
            continue
        reason = e.get("reason", "")
        if reason:
            reason = reason.split(".")[0] + "." if "." in reason else reason
        validated.append({
            "intent_id": intent_id,
            "question": question,
            "reason": reason or None,
        })
    return validated[:20]


def _find_superseded(
    artifact_store: ArtifactStore,
    chunk_ref: str,
) -> str | None:
    existing = artifact_store.list_by_type("quro.not_what_is.chunk")
    for ea in existing:
        payload = json.loads(ea.content)
        if payload.get("chunk_ref") == chunk_ref:
            return ea.artifact_id
    return None


def _load_intent_registry(artifact_store: ArtifactStore) -> dict[str, str]:
    registry: dict[str, str] = {}
    for art in artifact_store.list_by_type("quro.not_what_is.chunk"):
        payload = json.loads(art.content)
        for entry in payload.get("unanswered", []):
            if entry.get("intent_id") and entry.get("question"):
                registry[entry["intent_id"]] = entry["question"]
    for art in artifact_store.list_by_type("quro.canonical_question.doc"):
        payload = json.loads(art.content)
        for q in payload.get("questions", []):
            qid = q.get("question_id", "")
            if qid:
                registry[qid] = q.get("text", "")
    return registry


def _discover_chunks(config: QuroConfig) -> list[str]:
    raw_dir = os.path.join(config.storage_root, "raw")
    try:
        return sorted([
            f.replace(".txt", "") for f in os.listdir(raw_dir) if f.endswith(".txt")
        ])
    except FileNotFoundError:
        return []


def _load_chunk_text(chunk_ref: str, config: QuroConfig) -> str:
    raw_path = os.path.join(config.storage_root, "raw", f"{chunk_ref}.txt")
    try:
        with open(raw_path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


def _compute_input_snapshot_id(chunk_ref: str, config: QuroConfig) -> str:
    raw_path = os.path.join(config.storage_root, "raw", f"{chunk_ref}.txt")
    try:
        with open(raw_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return "unknown"


def _generate_unanswered(
    chunk_text: str,
    intent_registry: dict[str, str],
    max_entries: int,
    config: QuroConfig,
) -> list[dict]:
    try:
        from openai import OpenAI
        client_kwargs = {}
        if os.getenv("CANONICAL_QUESTIONS_API_URL"):
            client_kwargs["base_url"] = os.getenv("CANONICAL_QUESTIONS_API_URL")
            client_kwargs["timeout"] = float(os.getenv("CANONICAL_QUESTIONS_TIMEOUT", 10000000))
        print(f"Using OpenAI client with kwargs: {client_kwargs}")
        client = OpenAI(**client_kwargs)

        intent_list = "\n".join(
            f"- {k}: {v}" for k, v in list(intent_registry.items())[:50]
        )
        prompt = render(
            "not_what_is.j2",
            max_entries=max_entries,
            intent_list=intent_list,
            chunk_text=chunk_text,
        )
        resp = client.chat.completions.create(
            model=config.not_what_is_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=config.not_what_is_temperature,
            max_tokens=config.not_what_is_max_tokens,
        )
        print(f"Raw response content: {resp}")
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        entries = json.loads(content)
        if isinstance(entries, list):
            return entries
        return []
    except Exception as exc:
        print(f"Error generating unanswered for chunk: {exc}")
        return []


def run_not_what_is_pipeline(
    config: QuroConfig | None = None,
    chunk_refs: list[str] | None = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    dry_run: bool = False,
    extractor_version: str = DEFAULT_EXTRACTOR_VERSION,
) -> dict:
    config = config or QuroConfig.load()
    if not config.not_what_is_enabled:
        return {"status": "disabled"}

    artifact_store = ArtifactStore(config)
    provenance_tracker = ProvenanceTracker()
    pipeline_run_id = f"nwi_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    intent_registry = _load_intent_registry(artifact_store)
    created = 0
    errors = []

    chunk_refs = chunk_refs or _discover_chunks(config)
    for chunk_ref in chunk_refs:
        chunk_text = _load_chunk_text(chunk_ref, config)
        if not chunk_text:
            errors.append({"chunk_ref": chunk_ref, "error": "empty_chunk"})
            continue

        raw = _generate_unanswered(chunk_text, intent_registry, max_entries, config)
        validated = _validate_unanswered(raw)
        if not validated:
            errors.append({"chunk_ref": chunk_ref, "error": "all_entries_invalid"})
            continue

        if dry_run:
            created += 1
            continue

        artifact_id = f"nwi_{chunk_ref}"
        input_snapshot_id = _compute_input_snapshot_id(chunk_ref, config)
        model_version = config.not_what_is_model
        provenance = provenance_tracker.record(
            source_refs=[chunk_ref],
            extractor="not_what_is_pipeline",
            model_version=model_version,
            pipeline_run_id=pipeline_run_id,
            input_snapshot_id=input_snapshot_id,
        )

        supersedes = _find_superseded(artifact_store, chunk_ref)
        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type="quro.not_what_is.chunk",
            schema_version="1.2",
            kind="evidence",
            source_docs=[chunk_ref],
            content=json.dumps({
                "id": artifact_id,
                "chunk_ref": chunk_ref,
                "schema_version": "1.2",
                "generation_info": {
                    "extractor": "not_what_is_pipeline",
                    "model_version": model_version,
                    "pipeline_run_id": pipeline_run_id,
                    "input_snapshot_id": input_snapshot_id,
                },
                "unanswered": validated,
                "supersedes": supersedes,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False),
            confidence=1.0,
            freshness=1.0,
            model_version=model_version,
            provenance=provenance,
            supersedes=supersedes,
        )
        artifact_store.save(artifact)
        created += 1

    return {
        "status": "ok" if not errors else "partial",
        "chunks_processed": len(chunk_refs),
        "artifacts_created": created,
        "pipeline_run_id": pipeline_run_id,
        "errors": errors or None,
    }
