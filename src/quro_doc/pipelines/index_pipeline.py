"""Index pipeline: chunk -> embed -> upsert to vector store.

Called by worker after document is written to raw storage.
"""

import os
import json
from datetime import datetime, timezone
from ..storage import get_storage_root
from ..vector_adapter import get_adapter
from ..vector_adapter.embedding import embed_texts
from ..vector_adapter.base import PROTOCOL_VERSION


def _chunk_text(text: str, max_chars: int = 512) -> list[str]:
    paragraphs = text.split("\n\n")
    chunks = []
    buffer = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(buffer) + len(para) < max_chars:
            buffer = (buffer + "\n\n" + para).strip()
        else:
            if buffer:
                chunks.append(buffer)
            buffer = para
    if buffer:
        chunks.append(buffer)
    if not chunks:
        chunks = [text[:max_chars]]
    return chunks


def run_index_pipeline(doc_id: str):
    root = get_storage_root()
    raw_text = None
    for sub in ("docs", "raw"):
        raw_path = os.path.join(root, sub, f"{doc_id}.txt")
        if os.path.exists(raw_path):
            try:
                raw_text = open(raw_path, "r", encoding="utf-8").read()
            except Exception:
                continue
            break
    if not raw_text:
        return

    namespace = os.getenv("VECTOR_STORE_NAMESPACE", "default")

    chunks = _chunk_text(raw_text)
    texts = chunks
    embeddings = embed_texts(texts)

    adapter = get_adapter()
    records = []
    for i, (chunk_text, emb) in enumerate(zip(chunks, embeddings)):
        chunk_id = f"{doc_id}::chunk::{i}"
        records.append({
            "id": chunk_id,
            "embedding": emb,
            "metadata": {
                "doc_id": doc_id,
                "chunk_index": i,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "snippet": chunk_text[:200],
            },
            "namespace": namespace,
        })

    result = adapter.upsert_vectors({"records": records, "overwrite": True})

    meta = adapter.get_meta()
    meta["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    meta_path = os.path.join(get_storage_root(), "index", namespace, "meta.json")
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
