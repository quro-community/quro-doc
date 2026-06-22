from __future__ import annotations
import os
import json
import hashlib
from datetime import datetime, timezone

from ...config import QuroConfig
from ...artifacts.store import ArtifactStore, Artifact
from ...prompts import render


def _classify_confidence(answer: str, chunk_text: str) -> str | None:
    if "insufficient information" in answer.lower():
        return None
    key_sentences = [s.strip() for s in answer.split(".") if len(s.strip()) > 20]
    verbatim_count = sum(1 for s in key_sentences if s in chunk_text)
    total = len(key_sentences) or 1
    ratio = verbatim_count / total
    if ratio >= 0.8:
        return "directly_supported"
    elif ratio >= 0.3:
        return "weakly_inferred"
    return "speculative"


def _load_chunk_text(chunk_ref: str, config: QuroConfig) -> str:
    raw_path = os.path.join(config.storage_root, "raw", f"{chunk_ref}.txt")
    try:
        with open(raw_path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


def generate(
    intent_id: str,
    question: str,
    source_chunk_refs: list[str],
    config: QuroConfig,
) -> dict | None:
    if not config.not_what_is_supplement_model:
        return None

    chunk_texts = []
    for ref in source_chunk_refs:
        text = _load_chunk_text(ref, config)
        if text:
            chunk_texts.append(text)

    if not chunk_texts:
        return None

    combined = "\n\n---\n\n".join(chunk_texts)

    try:
        from openai import OpenAI
        client_kwargs = {}
        if os.getenv("CANONICAL_QUESTIONS_API_URL"):
            client_kwargs["base_url"] = os.getenv("CANONICAL_QUESTIONS_API_URL")
        client = OpenAI(**client_kwargs)

        prompt = render(
            "supplement_answer.j2",
            intent_id=intent_id,
            question=question,
            combined=combined,
        )
        resp = client.chat.completions.create(
            model=config.not_what_is_supplement_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=512,
        )
        answer = resp.choices[0].message.content.strip()
    except Exception:
        return None

    confidence = _classify_confidence(answer, combined)
    if confidence is None:
        return None

    content_hash = hashlib.sha256(answer.encode()).hexdigest()[:12]
    artifact_id = f"sup_{intent_id}_{content_hash}"

    return {
        "artifact_id": artifact_id,
        "intent_id": intent_id,
        "source_chunk_refs": source_chunk_refs,
        "generated_answer": answer,
        "confidence": confidence,
        "generation_info": {
            "model": config.not_what_is_supplement_model,
            "model_version": "1.0",
            "prompt_hash": hashlib.sha256(
                question.encode() + combined.encode()
            ).hexdigest()[:12],
        },
        "review_status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def run_supplement_generation(config: QuroConfig | None = None) -> dict:
    config = config or QuroConfig.load()
    if not config.not_what_is_supplement_enabled:
        return {"status": "disabled"}

    artifact_store = ArtifactStore(config)
    resolved_artifacts = artifact_store.list_by_type("quro.coverage.resolved")
    if not resolved_artifacts:
        return {
            "status": "ok",
            "supplements_created": 0,
            "message": "no resolved entries found",
        }

    latest = max(
        resolved_artifacts,
        key=lambda a: a.created_at or datetime.min.replace(tzinfo=timezone.utc),
    )
    resolved_entries = json.loads(latest.content)

    globally_missing = [
        r for r in resolved_entries if r["coverage_state"] == "globally_missing"
    ]
    created = 0
    errors = []

    for entry in globally_missing:
        supplement = generate(
            intent_id=entry["intent_id"],
            question=entry["canonical_question"],
            source_chunk_refs=[entry["source_chunk_ref"]],
            config=config,
        )
        if supplement is None:
            errors.append({
                "intent_id": entry["intent_id"],
                "error": "insufficient_information",
            })
            continue

        artifact = Artifact(
            artifact_id=supplement["artifact_id"],
            artifact_type="quro.supplement.proposed",
            schema_version="1.0",
            kind="evidence",
            source_docs=supplement["source_chunk_refs"],
            content=json.dumps(supplement, ensure_ascii=False),
            confidence=1.0,
            freshness=1.0,
            model_version=config.not_what_is_supplement_model,
            provenance=None,
        )
        artifact_store.save(artifact)
        created += 1

    return {
        "status": "ok" if not errors else "partial",
        "supplements_created": created,
        "globally_missing_total": len(globally_missing),
        "errors": errors or None,
    }
