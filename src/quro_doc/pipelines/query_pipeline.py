"""Multi-level search pipeline: InputNormalizer -> SmallRetriever -> ScoringEngine -> Reranker -> ContextAssembler.

Each stage is independently configurable. Falls back to raw scan
when no vector adapter is available.
"""

import os
import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from ..storage import get_storage_root
from ..vector_adapter.embedding import embed_text
from ..config import QuroConfig
from ..trace.model import (
    Trace, EvidenceFlow, CandidateSnapshot, Provenance,
    FinalAssembly, TraceTelemetry,
)


def _normalize(query: str) -> str:
    return query.strip()


def _load_raw_meta(doc_id: str) -> dict:
    root = get_storage_root()
    for sub in ("docs", "raw"):
        path = os.path.join(root, sub, f"{doc_id}.json")
        if os.path.exists(path):
            try:
                return json.loads(open(path, "r", encoding="utf-8").read())
            except Exception:
                continue
    return {}


def _raw_scan(query: str, top_k: int) -> List[Dict[str, Any]]:
    root = get_storage_root()
    results = []
    seen_ids: set = set()
    for sub in ("docs", "raw"):
        scan_dir = os.path.join(root, sub)
        if not os.path.isdir(scan_dir):
            continue
        for fname in os.listdir(scan_dir):
            if not fname.endswith(".json"):
                continue
            try:
                meta_path = os.path.join(scan_dir, fname)
                with open(meta_path, "r", encoding="utf-8") as fh:
                    meta = json.loads(fh.read())
            except Exception:
                continue
            doc_id = meta.get("doc_id") or fname.replace(".json", "")
            if doc_id in seen_ids:
                continue
            body_path = os.path.join(scan_dir, f"{doc_id}.txt")
            try:
                body = open(body_path, "r", encoding="utf-8").read()
            except Exception:
                continue
            if not body:
                continue
            seen_ids.add(doc_id)
            score = 0.0
            snippet = ""
            if query.lower() in body.lower():
                score = float(body.lower().count(query.lower()))
                idx = body.lower().find(query.lower())
                start = max(0, idx - 80)
                end = min(len(body), idx + len(query) + 80)
                snippet = body[start:end].replace("\n", " ")
            else:
                score = 0.1
                snippet = body[:200].replace("\n", " ")
            if score > 0:
                results.append({"doc_id": doc_id, "score": score, "snippet": snippet, "body": body})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


def _small_retriever(query: str, top_k: int) -> List[Dict[str, Any]]:
    try:
        from ..vector_adapter import get_adapter
        adapter = get_adapter()
        query_emb = embed_text(query)
        result = adapter.query_vectors({
            "query_embedding": query_emb,
            "top_k": top_k,
        })
        hits = result.get("hits", [])
        root = get_storage_root()
        for h in hits:
            doc_id = h.get("doc_id", "")
            body = ""
            for sub in ("docs", "raw"):
                body_path = os.path.join(root, sub, f"{doc_id}.txt")
                if os.path.exists(body_path):
                    try:
                        body = open(body_path, "r", encoding="utf-8").read()
                    except Exception:
                        pass
                    break
            h["body"] = body
        return hits
    except Exception:
        return []


def _score_hits(query: str, hits: List[Dict[str, Any]], query_tags: List[str]) -> List[Dict[str, Any]]:
    from ..scoring.engine import ScoringEngine
    engine = ScoringEngine.from_env()

    scored = []
    for hit in hits:
        doc_id = hit.get("doc_id", "")
        raw_meta = _load_raw_meta(doc_id)
        doc = dict(hit)
        doc.update(raw_meta)
        context = {"query_tags": query_tags}
        score, breakdown = engine.score(query, doc, context)
        if score is not None:
            hit["score"] = score
            hit["score_breakdown"] = breakdown
        scored.append(hit)
    scored.sort(key=lambda h: h.get("score", 0.0), reverse=True)
    return scored


def _rerank_hits(query: str, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if os.getenv("QUERY_USE_RERANKER", "false").lower() != "true":
        return hits
    from ..reranker.reranker import RerankerClient
    reranker = RerankerClient.from_env()
    try:
        reranked = reranker.rerank(query, hits)
        if reranked is not None:
            return reranked
    except Exception:
        pass
    return hits


def _run_artifact_pipeline(
    hits: List[Dict[str, Any]],
    config: "QuroConfig",
) -> None:
    if not config.artifact_store_enabled:
        return
    try:
        from ..artifacts.store import ArtifactStore
        from ..artifacts.feature_extractor import ArtifactFeatureExtractor
        from ..ranking.policy import RankingPolicy
        from ..view.candidate import EvidenceCandidate

        store = ArtifactStore(config)
        doc_ids = set(h.get("doc_id", "") for h in hits if h.get("doc_id"))
        artifacts = []
        for did in doc_ids:
            artifacts.extend(store.list_by_doc(did))

        if not artifacts:
            return

        extractor = ArtifactFeatureExtractor()
        candidates = []
        for h in hits:
            candidates.append(EvidenceCandidate.from_chunk(
                doc_id=h.get("doc_id", ""),
                chunk_id=h.get("chunk_id", h.get("id", "")),
                content=h.get("body", h.get("snippet", "")),
                source_type="raw",
                tags=h.get("tags"),
            ))

        features = extractor.extract(candidates, artifacts)
        candidate_ids = [c.candidate_id for c in candidates]

        policy = RankingPolicy(
            weights={
                "semantic_match": config.artifact_feature_weight,
                "canonical_alignment": config.artifact_feature_weight * 0.5,
                "qa_reuse_probability": config.artifact_feature_weight * 0.3,
                "summary_density": config.artifact_feature_weight * 0.2,
                "contradiction_risk": config.artifact_feature_weight * -0.5,
            },
            policy_id="artifact_policy",
            policy_version="1.0.0",
        )
        decision = policy.evaluate(features, candidate_ids)

        for i, h in enumerate(hits):
            h["artifact_feature"] = {
                "semantic_match": features[i].semantic_match,
                "canonical_alignment": features[i].canonical_alignment,
                "qa_reuse_probability": features[i].qa_reuse_probability,
                "summary_density": features[i].summary_density,
                "contradiction_risk": features[i].contradiction_risk,
                "token_cost": features[i].token_cost,
            }
            d = next((d for d in decision.decisions if d.candidate_id == candidate_ids[i]), None)
            if d:
                h["ranking_decision"] = {
                    "rank": d.rank,
                    "score": d.score,
                    "action": d.action,
                    "reason": d.reason,
                }
    except Exception:
        return


def _assemble(hits: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    results = []
    root = get_storage_root()
    for hit in hits[:top_k]:
        doc_id = hit.get("doc_id", "")
        body = hit.get("body", "")
        if not body:
            for sub in ("docs", "raw"):
                body_path = os.path.join(root, sub, f"{doc_id}.txt")
                if os.path.exists(body_path):
                    try:
                        body = open(body_path, "r", encoding="utf-8").read()
                    except Exception:
                        pass
                    break
        snippet = hit.get("snippet", "")
        if not snippet:
            snippet = body[:200].replace("\n", " ")

        raw_meta = _load_raw_meta(doc_id)
        raw_tags = raw_meta.get("meta", {}).get("tags", [])

        result = {
            "doc_id": doc_id,
            "chunk_id": hit.get("id", doc_id),
            "score": hit.get("score", 0.0),
            "snippet": snippet,
            "tags": raw_tags if raw_tags else None,
            "content": body,
            "tokens": len(body.split()),
            "source_type": "raw",
        }
        if "score_breakdown" in hit:
            result["score_breakdown"] = hit["score_breakdown"]
        if "artifact_feature" in hit:
            result["artifact_feature"] = hit["artifact_feature"]
        if "ranking_decision" in hit:
            result["ranking_decision"] = hit["ranking_decision"]
        results.append(result)
    return results


def _classify_result_status(
    assembled_results: List,
    storage_has_docs: bool,
) -> str:
    if assembled_results:
        return "ok"
    if not storage_has_docs:
        return "empty_expected"
    return "empty_unexpected"


def enrich_legacy_results(results: List[Dict]) -> List:
    from ..view.candidate import EvidenceCandidate
    from ..trace.model import Provenance
    ev_list = []
    for r in results:
        ev = EvidenceCandidate.from_chunk(
            doc_id=r.get("doc_id", ""),
            chunk_id=r.get("chunk_id", ""),
            content=r.get("content", r.get("snippet", "")),
            source_type=r.get("source_type", "raw"),
            tags=r.get("tags"),
        )
        if "score_breakdown" in r:
            ev.retrieval_signal.update(r["score_breakdown"])
        if "score" in r:
            ev.retrieval_signal["rerank_relevance"] = r["score"]
        if "artifact_feature" in r:
            ev.artifact_feature.update(r["artifact_feature"])
        if "ranking_decision" in r:
            ev.artifact_feature["ranking_decision"] = r["ranking_decision"]
        ev.runtime_cost["token_cost"] = r.get("tokens", len(ev.content.split()))
        ev_list.append(ev)
    return ev_list


def _capture_candidates(hits: List[Dict]) -> List[CandidateSnapshot]:
    snapshots = []
    for h in hits:
        snapshots.append(CandidateSnapshot(
            candidate_id=h.get("doc_id", ""),
            content_ref=h.get("doc_id", ""),
            source_type=h.get("source_type", "raw"),
            retrieval_signal={"similarity": h.get("score", 0.0), "rerank_relevance": h.get("score", 0.0)},
            artifact_feature=h.get("artifact_feature", {}),
            runtime_cost={"token_cost": h.get("tokens", 0), "latency_cost": 0, "redundancy_cost": 0},
            provenance=[Provenance(
                source_doc_id=h.get("doc_id", ""),
                pipeline_stage="retrieval",
                timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )],
        ))
    return snapshots


def search(query_dict: Dict[str, Any]) -> Any:
    config = QuroConfig.load()
    q = _normalize(query_dict.get("query", ""))
    top_k = int(query_dict.get("top_k", 10))
    query_tags = query_dict.get("tags", [])
    view_name = query_dict.get("view") or config.view_name

    root = get_storage_root()
    docs_dir = os.path.join(root, "docs")
    raw_dir = os.path.join(root, "raw")
    storage_has_docs = (
        (os.path.isdir(docs_dir) and bool(os.listdir(docs_dir)))
        or (os.path.isdir(raw_dir) and bool(os.listdir(raw_dir)))
    )

    t_start = time.time()
    results, evidence_flow = _legacy_search_with_evidence(q, top_k, query_tags, config=config)
    retrieval_latency = (time.time() - t_start) * 1000

    result_status = _classify_result_status(results, storage_has_docs)

    import uuid
    from ..view.engine import ViewLayerOrchestrator
    trace_id = query_dict.get("trace_id", str(uuid.uuid4()))
    rt_policy = config.snapshot()
    rt_versions = config.to_runtime_versions()

    if view_name in ("default", "default-view"):
        if view_name == "default-view":
            from ..view.renderer.base import ViewTelemetry
            telemetry = ViewTelemetry(
                trace_id=trace_id,
                view_name="default-view",
                result_status=result_status,
                candidates_considered=len(results),
                candidates_selected=len(results),
            )
            result = {
                "results": results,
                "telemetry": telemetry.to_dict(),
            }
            rendered_for_trace = result if query_dict.get("view") is not None else results
            _capture_and_save_trace(
                config=config, trace_id=trace_id, query_text=q,
                query_params=query_dict, evidence_flow=evidence_flow,
                rendered=rendered_for_trace, retrieval_latency=retrieval_latency,
                rt_policy=rt_policy, rt_versions=rt_versions,
            )
            if query_dict.get("view") is None:
                return results
            return result

        rendered_for_trace = results
        _capture_and_save_trace(
            config=config, trace_id=trace_id, query_text=q,
            query_params=query_dict, evidence_flow=evidence_flow,
            rendered=rendered_for_trace, retrieval_latency=retrieval_latency,
            rt_policy=rt_policy, rt_versions=rt_versions,
        )
        return results

    # Standard View rendering
    ev_candidates = enrich_legacy_results(results)
    orchestrator = ViewLayerOrchestrator()
    rendered = orchestrator.render(
        view_name=view_name,
        candidates=ev_candidates,
        query_text=q,
        trace_id=trace_id,
        query_params=query_dict,
        config=config,
    )

    # Trace capture (post-render, non-blocking)
    _capture_and_save_trace(
        config=config,
        trace_id=trace_id,
        query_text=q,
        query_params=query_dict,
        evidence_flow=evidence_flow,
        rendered=rendered,
        retrieval_latency=retrieval_latency,
        rt_policy=rt_policy,
        rt_versions=rt_versions,
    )

    if isinstance(rendered, dict) and "content" in rendered:
        return rendered["content"]
    return str(rendered)


def _legacy_search_with_evidence(q: str, top_k: int, query_tags: List[str], config: Optional[QuroConfig] = None) -> tuple:
    use_scoring = os.getenv("QUERY_USE_SCORING", "true").lower() == "true"
    use_reranker = os.getenv("QUERY_USE_RERANKER", "false").lower() == "true"

    try:
        hits = _small_retriever(q, top_k * 2)
    except Exception:
        hits = []

    if not hits:
        hits = _raw_scan(q, top_k * 2)
        if not hits:
            return [], EvidenceFlow(candidates_before_rerank=[])

    before_rerank = _capture_candidates(hits)

    if use_scoring:
        hits = _score_hits(q, hits, query_tags)

    after_rerank = None
    if use_reranker:
        hits = _rerank_hits(q, hits)
        after_rerank = _capture_candidates(hits)

    if config is None:
        config = QuroConfig.load()
    _run_artifact_pipeline(hits, config)

    results = _assemble(hits, top_k)

    evidence_flow = EvidenceFlow(
        candidates_before_rerank=before_rerank,
        candidates_after_rerank=after_rerank,
        candidates_after_prune=None,
    )

    return results, evidence_flow


def _capture_and_save_trace(
    config: QuroConfig,
    trace_id: str,
    query_text: str,
    query_params: dict,
    evidence_flow: EvidenceFlow,
    rendered: dict,
    retrieval_latency: float,
    rt_policy,
    rt_versions,
) -> None:
    try:
        from ..trace.store import TraceStore
        from ..view.renderer.base import QueryContext
        from ..trace.model import Trace, FinalAssembly, TraceTelemetry

        content = rendered.get("content", "") if isinstance(rendered, dict) else str(rendered)
        token_count = len(content.split())

        tlm = rendered.get("telemetry", {}) if isinstance(rendered, dict) else {}
        rerank_latency = tlm.get("rerank_latency_ms") if isinstance(tlm, dict) else None

        trace = Trace(
            trace_id=trace_id,
            timestamp=datetime.now(timezone.utc),
            query=QueryContext(text=query_text, trace_id=trace_id, params=query_params),
            policy=rt_policy,
            versions=rt_versions,
            evidence_flow=evidence_flow,
            assembly=FinalAssembly(
                selected_candidates=[c.candidate_id for c in (evidence_flow.candidates_after_rerank or evidence_flow.candidates_before_rerank)],
                rendered_context=content,
                token_usage=token_count,
            ),
            telemetry=TraceTelemetry(
                retrieval_latency_ms=retrieval_latency,
                rerank_latency_ms=rerank_latency,
                candidate_count_before_rerank=len(evidence_flow.candidates_before_rerank),
            ),
            feature_flags={
                "artifact_store_enabled": config.artifact_store_enabled,
            },
        )
        store = TraceStore(config)
        store.save(trace)
    except Exception:
        pass
