import os
import json
from typing import Dict, Any, List, Optional

import requests


class RerankerClient:
    def __init__(self, api_url: str, model: str, top_k: int):
        self.api_url = api_url
        self.model = model
        self.top_k = top_k

    def rerank(self, query: str, hits: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        candidates = hits[:self.top_k]
        if not candidates:
            return None

        docs = []
        for h in candidates:
            body = h.get("body", "")
            if not body:
                body = h.get("snippet", "")
            docs.append(body)

        import logging
        logger = logging.getLogger(__name__)
        try:
            body = {"model": self.model, "query": query, "documents": docs}
            logger.info("rerank request url=%s model=%s docs=%d query_len=%d",
                        self.api_url, self.model, len(docs), len(query))
            resp = requests.post(self.api_url, json=body, timeout=30)
            if not resp.ok:
                logger.error("rerank failed status=%d body=%s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
            data = resp.json()
            logger.info("rerank OK results=%d", len(data.get("results", [])))
        except Exception as e:
            logger.error("rerank exception: %s", str(e), exc_info=True)
            return None

        results = data.get("results", [])
        if not results:
            return None

        result_map = {r["index"]: r["relevance_score"] for r in results}
        for i, hit in enumerate(candidates):
            score = result_map.get(i)
            if score is not None:
                hit["score"] = score

        candidates.sort(key=lambda h: h.get("score", 0.0), reverse=True)
        return candidates

    @staticmethod
    def from_env() -> "RerankerClient":
        api_url = os.getenv("RERANK_API_URL", "http://localhost:8002/v1/rerank")
        model = os.getenv("RERANK_MODEL", "gpustack/bge-reranker-v2-m3")
        top_k = int(os.getenv("RERANK_TOP_K", "20"))
        return RerankerClient(api_url=api_url, model=model, top_k=top_k)
