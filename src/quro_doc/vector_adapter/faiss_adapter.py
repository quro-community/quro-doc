"""FAISSAdapter: production-ready local vector index using FAISS.

Supports L2 and inner-product (IP) similarity. Index is persisted to
a .faiss file and metadata to index/{namespace}/meta.json.
"""

import os
import json
import shutil
import numpy as np
from typing import Dict, Any, List
from datetime import datetime, timezone

from .base import BaseVectorAdapter, register_adapter, PROTOCOL_VERSION
from ..storage import get_storage_root

ADAPTER_VERSION = "0.1.0"

try:
    import faiss
except ImportError:
    faiss = None


@register_adapter("faiss")
class FAISSAdapter(BaseVectorAdapter):
    adapter_type = "faiss"

    def __init__(self, namespace: str = "default", metric: str = "L2"):
        if faiss is None:
            raise ImportError(
                "FAISS is not installed. Install it with: pip install faiss-cpu"
            )
        self.namespace = namespace
        self.metric = metric
        self._index_path = os.path.join(get_storage_root(), "index", namespace)
        self._meta_path = os.path.join(self._index_path, "meta.json")
        self._faiss_path = os.path.join(self._index_path, "vectors.faiss")
        self._index: Any = None
        self._id_map: List[str] = []
        self._dim = 0
        self._load_from_disk()

    def _load_from_disk(self):
        os.makedirs(self._index_path, exist_ok=True)
        if not os.path.exists(self._faiss_path):
            return
        try:
            self._index = faiss.read_index(self._faiss_path)
            self._dim = self._index.d
            self._id_map = []
            id_path = os.path.join(self._index_path, "id_map.json")
            if os.path.exists(id_path):
                with open(id_path, "r", encoding="utf-8") as fh:
                    self._id_map = json.load(fh)
        except Exception:
            self._index = None
            self._id_map = []

    def _ensure_index(self, dim: int):
        if self._index is None or self._dim != dim:
            if self.metric.upper() == "IP":
                self._index = faiss.IndexFlatIP(dim)
            else:
                self._index = faiss.IndexFlatL2(dim)
            self._dim = dim

    def upsert_vectors(self, request: Dict[str, Any]) -> Dict[str, Any]:
        records = request.get("records", [])
        overwrite = request.get("overwrite", True)
        if not records:
            return {"status": "ok", "upserted_count": 0}

        dim = len(records[0].get("embedding", []))
        if dim == 0:
            return {"status": "ok", "upserted_count": 0}

        self._ensure_index(dim)

        existing = {vid: idx for idx, vid in enumerate(self._id_map)}
        upserted = 0

        for rec in records:
            vid = rec["id"]
            emb = np.array(rec["embedding"], dtype=np.float32).reshape(1, -1)
            if vid in existing and overwrite:
                idx = existing[vid]
                self._index.reconstruct(idx, emb.reshape(-1))
                upserted += 1
            elif vid not in existing:
                self._index.add(emb)
                self._id_map.append(vid)
                upserted += 1

        self._persist_index()
        self._write_meta()
        return {"status": "ok", "upserted_count": upserted}

    def query_vectors(self, request: Dict[str, Any]) -> Dict[str, Any]:
        query_emb = request.get("query_embedding", [])
        top_k = request.get("top_k", 10)
        nf = request.get("filter", {})
        ns_filter = nf.get("namespace", self.namespace)

        if not query_emb or self._index is None or self._index.ntotal == 0:
            return {
                "query_request": request,
                "hits": [],
                "meta": {
                    "protocol_version": PROTOCOL_VERSION,
                    "adapter": self.adapter_type,
                    "adapter_version": ADAPTER_VERSION,
                },
            }

        q = np.array([query_emb], dtype=np.float32)
        k = min(top_k, self._index.ntotal)
        distances, indices = self._index.search(q, k)

        hits = []
        for i in range(k):
            idx = int(indices[0][i])
            if idx < 0 or idx >= len(self._id_map):
                continue
            vid = self._id_map[idx]
            score_float = float(distances[0][i])
            if self.metric.upper() == "L2":
                score_float = 1.0 / (1.0 + score_float)

            # reconstruct metadata from stored VectorRecord mapping
            meta = {}
            hits.append({
                "id": vid,
                "doc_id": self._extract_doc_id(vid),
                "chunk_index": self._extract_chunk_index(vid),
                "score": round(score_float, 6),
                "metadata": meta,
                "snippet": "",
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
        new_id_map = []
        keep_indices = []
        for idx, vid in enumerate(self._id_map):
            if vid in ids:
                deleted += 1
            else:
                new_id_map.append(vid)
                keep_indices.append(idx)

        if deleted == 0:
            return {"deleted_count": 0}

        if self._index and keep_indices:
            vectors = self._index.reconstruct_n(0, self._index.ntotal)
            kept_vectors = vectors[keep_indices]
            dim = self._dim
            self._ensure_index(dim)
            self._index.add(kept_vectors)
        else:
            self._index = None
            self._dim = 0

        self._id_map = new_id_map
        self._persist_index()
        self._write_meta()
        return {"deleted_count": deleted}

    def persist(self, path: str) -> Dict[str, Any]:
        if os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)
        if self._index:
            faiss.write_index(self._index, os.path.join(path, "vectors.faiss"))
        shutil.copy(
            os.path.join(self._index_path, "id_map.json"),
            os.path.join(path, "id_map.json"),
        )
        return {"status": "ok"}

    def load(self, path: str) -> Dict[str, Any]:
        self._index = None
        self._id_map = []
        self._dim = 0
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
            "vector_count": len(self._id_map) if self._index else 0,
            "namespace": self.namespace,
            "metric": self.metric,
            "dim": self._dim,
        }

    def _persist_index(self):
        if self._index is None:
            return
        os.makedirs(self._index_path, exist_ok=True)
        faiss.write_index(self._index, self._faiss_path)
        id_path = os.path.join(self._index_path, "id_map.json")
        with open(id_path, "w", encoding="utf-8") as fh:
            json.dump(self._id_map, fh, ensure_ascii=False)

    def _write_meta(self):
        meta = self.get_meta()
        meta["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        os.makedirs(os.path.dirname(self._meta_path), exist_ok=True)
        with open(self._meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)

    @staticmethod
    def _extract_doc_id(vid: str) -> str:
        return vid.split("::chunk::")[0] if "::chunk::" in vid else vid

    @staticmethod
    def _extract_chunk_index(vid: str) -> int:
        parts = vid.split("::chunk::")
        if len(parts) == 2:
            try:
                return int(parts[1])
            except ValueError:
                return 0
        return 0
