"""FSAdapter: file-system based vector store for local dev/testing.

Vectors are stored as JSON files under index/{namespace}/chunks/.
Full index is held in memory for fast query. Zero external dependencies.
"""

import os
import json
import shutil
from typing import Dict, Any, List
from datetime import datetime, timezone

from .base import BaseVectorAdapter, register_adapter, PROTOCOL_VERSION
from ..storage import get_storage_root

ADAPTER_VERSION = "0.1.0"


@register_adapter("fs")
class FSAdapter(BaseVectorAdapter):
    adapter_type = "fs"

    def __init__(self, namespace: str = "default"):
        self.namespace = namespace
        self._vectors: Dict[str, Dict[str, Any]] = {}
        self._index_path = os.path.join(get_storage_root(), "index", namespace)
        self._chunks_dir = os.path.join(self._index_path, "chunks")
        self._meta_path = os.path.join(self._index_path, "meta.json")
        self._load_from_disk()

    def _load_from_disk(self):
        if not os.path.exists(self._chunks_dir):
            os.makedirs(self._chunks_dir, exist_ok=True)
            return
        for fname in os.listdir(self._chunks_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self._chunks_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    record = json.load(fh)
                self._vectors[record["id"]] = record
            except Exception:
                continue

    def _write_chunk_file(self, record: Dict[str, Any]):
        safe_id = record["id"].replace("::", "__")
        path = os.path.join(self._chunks_dir, f"{safe_id}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False)

    def _delete_chunk_file(self, vid: str):
        safe_id = vid.replace("::", "__")
        path = os.path.join(self._chunks_dir, f"{safe_id}.json")
        if os.path.exists(path):
            os.remove(path)

    def upsert_vectors(self, request: Dict[str, Any]) -> Dict[str, Any]:
        records = request.get("records", [])
        overwrite = request.get("overwrite", True)
        upserted = 0
        for rec in records:
            vid = rec["id"]
            if not overwrite and vid in self._vectors:
                continue
            rec.setdefault("namespace", self.namespace)
            self._vectors[vid] = rec
            self._write_chunk_file(rec)
            upserted += 1
        self._write_meta()
        return {"status": "ok", "upserted_count": upserted}

    def query_vectors(self, request: Dict[str, Any]) -> Dict[str, Any]:
        query_emb = request.get("query_embedding", [])
        top_k = request.get("top_k", 10)
        nf = request.get("filter", {})
        ns_filter = nf.get("namespace", self.namespace)

        if not query_emb or not self._vectors:
            return {
                "query_request": request,
                "hits": [],
                "meta": {
                    "protocol_version": PROTOCOL_VERSION,
                    "adapter": self.adapter_type,
                    "adapter_version": ADAPTER_VERSION,
                },
            }

        scored = []
        for vid, rec in self._vectors.items():
            if rec.get("namespace", "default") != ns_filter:
                continue
            emb = rec.get("embedding", [])
            if not emb:
                continue
            score = self._cosine_similarity(query_emb, emb)
            scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        hits = []
        for score, rec in scored[:top_k]:
            meta = rec.get("metadata", {})
            hits.append({
                "id": rec["id"],
                "doc_id": meta.get("doc_id", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "score": round(float(score), 6),
                "metadata": meta,
                "snippet": meta.get("snippet", ""),
            })

        return {
            "query_request": request,
            "hits": hits,
            "meta": {
                "protocol_version": PROTOCOL_VERSION,
                "adapter": self.adapter_type,
                "adapter_version": ADAPTER_VERSION,
            },
        }

    def delete_vectors(self, ids: List[str]) -> Dict[str, Any]:
        deleted = 0
        for vid in ids:
            if vid in self._vectors:
                del self._vectors[vid]
                self._delete_chunk_file(vid)
                deleted += 1
        if deleted:
            self._write_meta()
        return {"deleted_count": deleted}

    def persist(self, path: str) -> Dict[str, Any]:
        if os.path.exists(path):
            shutil.rmtree(path)
        shutil.copytree(self._index_path, path)
        return {"status": "ok"}

    def load(self, path: str) -> Dict[str, Any]:
        self._vectors.clear()
        if os.path.exists(self._index_path):
            shutil.rmtree(self._index_path)
        shutil.copytree(path, self._index_path)
        self._load_from_disk()
        return {"status": "ok"}

    def get_meta(self) -> Dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "adapter": self.adapter_type,
            "adapter_version": ADAPTER_VERSION,
            "vector_count": len(self._vectors),
            "namespace": self.namespace,
        }

    def _write_meta(self):
        meta = self.get_meta()
        meta["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        os.makedirs(os.path.dirname(self._meta_path), exist_ok=True)
        with open(self._meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
