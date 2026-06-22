from __future__ import annotations
import os
import re
import json
import sys
import hashlib
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Any

from ...config import QuroConfig
from ...artifacts.store import ArtifactStore, Artifact
from ...artifacts.provenance import ProvenanceTracker
from ...prompts import render
from .hot_doc_scanner import HotDocScanner


DEFAULT_HOT_THRESHOLD = 3
DEFAULT_MAX_QUESTIONS = 5
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_EXTRACTOR_VERSION = "1.1.0"
SECTION_CHAR_LIMIT = 32000

# --- Controlled vocabularies ---

VALID_QUESTION_TYPES = {"conceptual", "design_rationale", "mechanism", "relationship"}

VALID_ENTITY_TYPES = {
    "concept", "design_principle", "algorithm",
    "data_structure", "process", "formula",
}

VALID_RELATIONS = {
    "contains", "computes", "depends_on", "feeds_into",
    "governs", "implements", "plugs_into", "relates_to",
}


@dataclass
class CQEntity:
    name: str
    entity_type: str = "concept"

    @classmethod
    def from_dict(cls, d: dict) -> CQEntity:
        return cls(name=d.get("name", ""), entity_type=d.get("entity_type", "concept"))

    def to_dict(self) -> dict:
        return {"name": self.name, "entity_type": self.entity_type}


@dataclass
class CQEdge:
    from_: str
    to: str
    relation: str

    @classmethod
    def from_dict(cls, d: dict) -> CQEdge:
        return cls(from_=d.get("from", ""), to=d.get("to", ""), relation=d.get("relation", ""))

    def to_dict(self) -> dict:
        return {"from": self.from_, "to": self.to, "relation": self.relation}


@dataclass
class CanonicalQuestion:
    question_id: str = ""
    text: str = ""
    question_type: str = "factual"
    confidence: float = 0.0
    extraction_method: str = "llm-low-temp"
    extractor_version: str = DEFAULT_EXTRACTOR_VERSION

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "text": self.text,
            "question_type": self.question_type,
            "confidence": self.confidence,
            "extraction_method": self.extraction_method,
            "extractor_version": self.extractor_version,
        }


@dataclass
class CQDocument:
    """Top-level container for a document's CQ extraction result."""
    source_ref: str
    questions: list[CanonicalQuestion] = field(default_factory=list)
    entities: list[CQEntity] = field(default_factory=list)
    edges: list[CQEdge] = field(default_factory=list)
    confidence: float = 0.0
    extractor_version: str = DEFAULT_EXTRACTOR_VERSION

    def to_payload(self) -> dict:
        return {
            "questions": [q.to_dict() for q in self.questions],
            "entities": [e.to_dict() for e in self.entities],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_payload(cls, source_ref: str, payload: dict) -> CQDocument:
        questions = []
        for q in payload.get("questions", []):
            cq = CanonicalQuestion(
                question_id=_compute_question_id(source_ref, q.get("text", ""), DEFAULT_EXTRACTOR_VERSION),
                text=q.get("text", ""),
                question_type=q.get("question_type", "factual"),
            )
            questions.append(cq)

        entities = [CQEntity.from_dict(e) for e in payload.get("entities", [])]
        edges = [CQEdge.from_dict(e) for e in payload.get("edges", [])]

        return cls(
            source_ref=source_ref,
            questions=questions,
            entities=entities,
            edges=edges,
        )


def _compute_question_id(source_ref: str, text: str, extractor_version: str) -> str:
    """Question ID hashes over source_ref + text for stable dedup."""
    normalized = " ".join(text.strip().lower().split())
    raw = f"{source_ref}|{normalized}|{extractor_version}"
    return f"cq_{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def _compute_input_snapshot_id(doc_id: str, config: QuroConfig) -> str:
    raw_path = os.path.join(config.storage_root, "raw", f"{doc_id}.txt")
    try:
        with open(raw_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return "unknown"


def _pre_process(body: str) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", body)
    sections = []
    current = ""
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(current) + len(p) > SECTION_CHAR_LIMIT:
            if current:
                sections.append(current)
            current = p
        else:
            current = (current + "\n\n" + p) if current else p
    if current:
        sections.append(current)
    return sections or [body[:SECTION_CHAR_LIMIT]]


def _call_llm(body: str, max_questions: int, config: QuroConfig) -> dict | None:
    """Call LLM with the two-step CQ + entities/edges prompt. Returns parsed JSON payload or None."""
    print(f"[CQ_TRACE] _call_llm entered, body_len={len(body)}, max_q={max_questions}", flush=True)
    try:
        from openai import OpenAI

        client_kwargs = {}
        if config.canonical_question_api_url:
            client_kwargs["base_url"] = config.canonical_question_api_url
        client = OpenAI(**client_kwargs)
        model = config.canonical_question_model

        prompt = render(
            "canonical_questions.j2",
            max_questions=max_questions,
            body=body,
            section_char_limit=SECTION_CHAR_LIMIT,
        )

        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=config.canonical_question_temperature,
            seed=config.canonical_question_seed,
        )

        raw_content = (resp.choices[0].message.content or "").strip()
        print(f"[CQ_RAW_START]", file=sys.stderr)
        print(repr(raw_content[:3000]), file=sys.stderr)
        print(f"[CQ_RAW_END]", file=sys.stderr)

        # Robust JSON extraction: try multiple strategies
        payload = _extract_json(raw_content)
        if payload is not None:
            print(f"[CQ_OK] extracted payload with {len(payload.get('questions',[]))} questions", file=sys.stderr, flush=True)
            return payload

        print(f"[CQ_FAIL] _extract_json returned None. raw[:2000]={raw_content[:2000]}", file=sys.stderr, flush=True)
        return None
    except Exception as e:
        print(f"[CQ_EXC] {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def _extract_json(text: str) -> dict | None:
    """
    Extract a JSON object from text using multiple strategies.
    1. Direct parse (if the entire text is a JSON object)
    2. Strip markdown code fences and parse
    3. Find the outermost { ... } and parse that substring
    """
    if not text:
        return None

    # Strategy 1: direct parse
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    # Strategy 2: strip code fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", text)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    if cleaned != text:
        try:
            payload = json.loads(cleaned)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

    # Strategy 3: find outermost { ... } object
    brace_start = text.find("{")
    if brace_start != -1:
        depth = 0
        for i in range(brace_start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        payload = json.loads(text[brace_start:i + 1])
                        if isinstance(payload, dict):
                            return payload
                    except json.JSONDecodeError:
                        pass
                    break

    # Strategy 4: try json.loads on the full text with strict=False
    try:
        payload = json.loads(cleaned)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    return None


def _validate_document(body: str, payload: dict) -> float:
    """
    Validate the entire CQ document payload (questions + entities + edges).
    Returns a confidence score 0.0–1.0 based on entity presence in body.
    """
    questions = payload.get("questions", [])
    entities = payload.get("entities", [])
    edges = payload.get("edges", [])

    # --- Question validations ---
    if not questions:
        return 0.0
    for q in questions:
        if not q.get("text", "").strip():
            return 0.0
        qtype = q.get("question_type")
        if qtype and qtype not in VALID_QUESTION_TYPES:
            return 0.0

    # --- Entity validations ---
    if len(entities) < 5:
        return 0.0
    if len(entities) > 12:
        return 0.0

    entity_names: set[str] = set()
    for ent in entities:
        name = ent.get("name", "").strip()
        etype = ent.get("entity_type", "")
        if not name:
            return 0.0
        if etype not in VALID_ENTITY_TYPES:
            return 0.0
        entity_names.add(name)

    # --- Edge validations ---
    if len(edges) < 4:
        return 0.0

    for edge in edges:
        from_name = edge.get("from", "")
        to_name = edge.get("to", "")
        rel = edge.get("relation", "")
        if from_name not in entity_names or to_name not in entity_names:
            return 0.0
        if rel not in VALID_RELATIONS:
            return 0.0

    # --- Entity presence in body ---
    body_lower = body.lower()
    found = sum(1 for name in entity_names if name.lower() in body_lower)
    if found == 0:
        return 0.0

    return found / len(entity_names)


_PRONOUN_STARTS = [
    "what are its", "what is its", "how does it", "why is it",
    "what does it", "what were its", "how do they", "why do they",
    "what is their", "what are their", "how does this",
]


def _is_context_dependent(text: str) -> bool:
    """Check if a question is missing entity references and depends on context."""
    lower = text.lower().strip()
    for p in _PRONOUN_STARTS:
        if lower.startswith(p):
            return True
    return False


def _is_near_duplicate(normalized: str, seen: set[str], threshold: float = 0.85) -> bool:
    words_a = set(normalized.split())
    for existing in seen:
        words_b = set(existing.split())
        if not words_a or not words_b:
            continue
        overlap = len(words_a & words_b)
        similarity = overlap / max(len(words_a), len(words_b))
        if similarity >= threshold:
            return True
    return False


def _filter_questions(questions: list[dict]) -> list[dict]:
    """Apply dedup and context-dependency filters to questions."""
    results = []
    seen_texts: set[str] = set()
    for q in questions:
        text = q.get("text", "").strip()
        if not text:
            continue
        if _is_context_dependent(text):
            continue
        normalized = " ".join(text.lower().split())
        if _is_near_duplicate(normalized, seen_texts):
            continue
        seen_texts.add(normalized)
        results.append(q)
    return results


def _load_doc_body(doc_id: str, config: QuroConfig) -> str:
    raw_path = os.path.join(config.storage_root, "raw", f"{doc_id}.txt")
    try:
        with open(raw_path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


def run_canonical_questions_pipeline(
    config: QuroConfig | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    hot_threshold: int = DEFAULT_HOT_THRESHOLD,
    max_questions: int = DEFAULT_MAX_QUESTIONS,
    dry_run: bool = False,
    extractor_version: str = DEFAULT_EXTRACTOR_VERSION,
    doc_ids: list[str] | None = None,
) -> dict:
    config = config or QuroConfig.load()

    if not config.canonical_question_enabled:
        return {"status": "disabled", "message": "canonical_question_enabled is False"}

    if doc_ids is not None:
        to_process = list(doc_ids)
        mode_note = "explicit"
    else:
        scanner = HotDocScanner(config)
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        hot_results = scanner.scan(since=since)
        to_process = [r.doc_id for r in hot_results if r.frequency >= hot_threshold]
        mode_note = "hot"

    if not to_process:
        return {"status": "ok", "docs_found": 0, "artifacts_created": 0, "message": "No documents to process"}

    artifact_store = ArtifactStore(config)
    provenance_tracker = ProvenanceTracker()
    pipeline_run_id = f"cq_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    created = 0
    errors = []

    for doc_id in to_process:
        body = _load_doc_body(doc_id, config)
        if not body:
            errors.append({"doc_id": doc_id, "error": "empty_body"})
            continue

        sections = _pre_process(body)
        best_payload: dict | None = None
        best_confidence = 0.0

        for section in sections:
            raw_payload = _call_llm(section, max_questions, config)
            if not raw_payload:
                continue
            print(raw_payload)

            confidence = _validate_document(section, raw_payload)
            if confidence > best_confidence:
                best_confidence = confidence
                best_payload = raw_payload

        if best_payload is None or best_confidence <= 0.0:
            reasons = []
            if best_payload is None:
                reasons.append("LLM returned None for all sections")
            else:
                # Debug dump the payload that failed validation
                qs = best_payload.get("questions", [])
                ents = best_payload.get("entities", [])
                edgs = best_payload.get("edges", [])
                reasons.append(f"validation failed (score={best_confidence})")
                reasons.append(f"questions={len(qs)}, entities={len(ents)}, edges={len(edgs)}")
                if qs:
                    for i, q in enumerate(qs):
                        reasons.append(f"  q[{i}]: text={q.get('text','')[:60]!r}, type={q.get('question_type','')!r}")
                if ents:
                    for i, e in enumerate(ents):
                        reasons.append(f"  e[{i}]: name={e.get('name','')!r}, type={e.get('entity_type','')!r}")
                if edgs:
                    for i, e in enumerate(edgs):
                        reasons.append(f"  edge[{i}]: from={e.get('from','')!r} to={e.get('to','')!r} rel={e.get('relation','')!r}")
                # Check entity presence in body
                for e in ents:
                    name = e.get("name", "")
                    present = name.lower() in body.lower() if name else False
                    reasons.append(f"  entity '{name}' in body: {present}")
            error_msg = "; ".join(reasons)
            print(f"[CQ_ERR] doc={doc_id}: {error_msg}", file=sys.stderr, flush=True)
            errors.append({"doc_id": doc_id, "error": "no_valid_output", "debug": error_msg})
            continue

        # Apply question filters
        raw_questions = best_payload.get("questions", [])
        filtered_questions = _filter_questions(raw_questions)
        if not filtered_questions:
            errors.append({"doc_id": doc_id, "error": "all_questions_filtered"})
            continue

        # Build CQDocument
        cq_doc = CQDocument.from_payload(doc_id, {
            "questions": filtered_questions,
            "entities": best_payload.get("entities", []),
            "edges": best_payload.get("edges", []),
        })
        cq_doc.confidence = best_confidence

        if dry_run:
            created += 1
            continue

        artifact_id = f"cq_set_{doc_id}"
        input_snapshot_id = _compute_input_snapshot_id(doc_id, config)
        model_version = config.canonical_question_model
        provenance = provenance_tracker.record(
            source_refs=[doc_id],
            extractor="canonical_questions_pipeline",
            model_version=model_version,
            pipeline_run_id=pipeline_run_id,
            input_snapshot_id=input_snapshot_id,
        )

        supersedes = None
        existing_artifacts = artifact_store.list_by_type("quro.canonical_question.doc")
        for ea in existing_artifacts:
            if doc_id in (ea.source_docs or []):
                supersedes = ea.artifact_id
                break

        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type="quro.canonical_question.doc",
            schema_version="1.1",
            kind="routing",
            source_docs=[doc_id],
            content=json.dumps(cq_doc.to_payload(), ensure_ascii=False),
            confidence=cq_doc.confidence,
            freshness=1.0,
            model_version=model_version,
            provenance=provenance,
            supersedes=supersedes,
        )
        artifact_store.save(artifact)
        created += 1

    return {
        "status": "ok" if not errors else "partial",
        "docs_found": len(to_process),
        "artifacts_created": created,
        "mode_note": mode_note,
        "dry_run": dry_run,
        "pipeline_run_id": pipeline_run_id,
        "errors": errors or None,
    }
