"""Simple file-based storage abstraction.

Directory layout (v2 local-first):
  {root}/docs/      — canonical document store (new writes go here)
  {root}/raw/       — legacy document store (read-only fallback)
  {root}/assets/    — binary asset store (images, PDFs, etc.)
  {root}/index/     — vector index data
  {root}/jobs/      — deferred job queue
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict
from .model import Field, MetaKey, ResponseKey


def get_storage_root() -> str:
    return os.getenv("QURO_STORAGE_ROOT", ".quro_context/docs")


def ensure_dirs(root: Optional[str] = None):
    root = root or get_storage_root()
    Path(root).mkdir(parents=True, exist_ok=True)
    for sub in ["docs", "raw", "assets", "index", "jobs", "registry", "events"]:
        Path(root, sub).mkdir(parents=True, exist_ok=True)


# ── Document path resolution (gradual migration) ─────────────────────


def _resolve_doc_path(doc_id: str, root: Optional[str] = None) -> Optional[Path]:
    """Resolve a document's base path, checking docs/ first then raw/.

    Returns the Path prefix (without extension) if found, else None.
    """
    if ".." in doc_id or doc_id.startswith("/"):
        return None
    root = Path(root or get_storage_root())
    docs_path = root / "docs" / doc_id
    if (docs_path.with_name(docs_path.name + ".txt")).exists():
        return docs_path
    raw_path = root / "raw" / doc_id
    if (raw_path.with_name(raw_path.name + ".txt")).exists():
        return raw_path
    return None


# ── Document CRUD ────────────────────────────────────────────────────


def write_raw_doc(doc_id: str, body: str, metadata: dict, root: Optional[str] = None) -> bool:
    """Write a new document to docs/. Returns False if already exists."""
    root = root or get_storage_root()
    ensure_dirs(root)
    # Check existence in both dirs (idempotency)
    if _resolve_doc_path(doc_id, root) is not None:
        return False
    docs_dir = Path(root, "docs")
    txt_path = docs_dir / f"{doc_id}.txt"
    meta_path = docs_dir / f"{doc_id}.json"
    try:
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        txt_path.write_text(body, encoding="utf-8")
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return False
    return True


def read_raw_doc(doc_id: str, root: Optional[str] = None) -> Optional[dict]:
    """Read a document from docs/ with fallback to raw/."""
    root = root or get_storage_root()
    base = _resolve_doc_path(doc_id, root)
    if base is None:
        return None
    txt_path = base.with_name(base.name + ".txt")
    meta_path = base.with_name(base.name + ".json")
    body = txt_path.read_text(encoding="utf-8")
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    return {Field.DOC_ID: doc_id, Field.BODY: body, MetaKey.META: meta}


def list_raw_docs(limit: int = 100, root: Optional[str] = None):
    """List documents from both docs/ and raw/, deduplicating by doc_id."""
    root = Path(root or get_storage_root())
    seen_ids: set = set()
    res: list = []

    # docs/ first (canonical)
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        for f in sorted(docs_dir.rglob("*.json"))[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                doc_id = data.get("doc_id") or f.stem
                seen_ids.add(doc_id)
                data["doc_id"] = doc_id
                res.append(data)
            except Exception:
                continue

    # raw/ fallback (skip already-seen)
    raw_dir = root / "raw"
    if raw_dir.is_dir():
        for f in sorted(raw_dir.rglob("*.json")):
            if len(res) >= limit:
                break
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                doc_id = data.get("doc_id") or f.stem
                if doc_id in seen_ids:
                    continue
                seen_ids.add(doc_id)
                data["doc_id"] = doc_id
                res.append(data)
            except Exception:
                continue

    return res


# ── Asset CRUD ───────────────────────────────────────────────────────


def _safe_asset_path(asset_id: str, root: Optional[str] = None) -> Path:
    """Resolve asset path with path-traversal guard."""
    root = root or get_storage_root()
    assets_dir = Path(root, "assets").resolve()
    asset_path = (assets_dir / asset_id).resolve()
    if not str(asset_path).startswith(str(assets_dir) + os.sep):
        raise ValueError(f"Invalid asset_id: {asset_id}")
    return asset_path


def put_asset(asset_id: str, data: bytes, content_type: str = "application/octet-stream",
              root: Optional[str] = None) -> bool:
    """Store a binary asset. Returns False if already exists."""
    root = root or get_storage_root()
    ensure_dirs(root)
    asset_path = _safe_asset_path(asset_id, root)
    if asset_path.exists():
        return False
    asset_path.write_bytes(data)
    meta_path = asset_path.with_name(asset_path.name + ".meta.json")
    meta_path.write_text(json.dumps({
        "asset_id": asset_id,
        "content_type": content_type,
        "size": len(data),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def get_asset(asset_id: str, root: Optional[str] = None) -> Optional[Dict]:
    """Retrieve an asset's data and metadata. Returns None if not found."""
    root = root or get_storage_root()
    asset_path = _safe_asset_path(asset_id, root)
    if not asset_path.exists():
        return None
    data = asset_path.read_bytes()
    meta = {}
    meta_path = asset_path.with_name(asset_path.name + ".meta.json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    return {ResponseKey.ASSET_ID: asset_id, "data": data, MetaKey.META: meta}


def delete_asset(asset_id: str, root: Optional[str] = None) -> bool:
    """Delete an asset. Returns True if deleted, False if not found."""
    root = root or get_storage_root()
    asset_path = _safe_asset_path(asset_id, root)
    if not asset_path.exists():
        return False
    asset_path.unlink()
    meta_path = asset_path.with_name(asset_path.name + ".meta.json")
    if meta_path.exists():
        meta_path.unlink()
    return True
