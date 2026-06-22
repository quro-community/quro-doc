"""Materialize pipeline — downloads pending assets and stores them via put_asset().

Supports dual materializer backend:
  - httpx  (MVP fast-path, default)
  - aria2  (standard crawler, set QURO_MATERIALIZER=aria2)

TDA role: Extension. Phase 3b of asset-aware writer pipeline.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, Any, List, Callable

import httpx

from ..storage import read_raw_doc, put_asset, get_storage_root
from ..storage_layer import StorageLayer


MATERIALIZER = os.environ.get("QURO_MATERIALIZER", "httpx")


# ── Materializer backends ─────────────────────────────────────────────


def _materialize_via_httpx(asset: Dict[str, Any], project: str | None = None) -> Dict[str, Any]:
    """MVP fast-path: download via httpx, store via put_asset()."""
    asset_id = asset["asset_id"]
    source_url = asset.get("source_url", "")
    source_type = asset.get("source_type", "unknown")

    if source_type not in ("https",):
        return {
            "asset_id": asset_id,
            "status": "skipped",
            "reason": f"source_type '{source_type}' not supported",
        }

    try:
        resp = httpx.get(source_url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        data = resp.content
        content_type = resp.headers.get("content-type", "application/octet-stream")

        root = None
        if project:
            layer = StorageLayer()
            root = layer.resolve_storage_root(project)

        wrote = put_asset(
            asset_id=asset_id,
            data=data,
            content_type=content_type,
            root=root,
        )
        if wrote:
            return {
                "asset_id": asset_id,
                "status": "downloaded",
                "source_url": source_url,
                "size": len(data),
                "content_type": content_type,
            }
        else:
            return {
                "asset_id": asset_id,
                "status": "skipped",
                "reason": "asset already exists",
            }
    except httpx.HTTPStatusError as e:
        return {
            "asset_id": asset_id,
            "status": "failed",
            "source_url": source_url,
            "error": f"HTTP {e.response.status_code}",
        }
    except Exception as e:
        return {
            "asset_id": asset_id,
            "status": "failed",
            "source_url": source_url,
            "error": str(e),
        }


def _materialize_via_aria2(asset: Dict[str, Any], project: str | None = None) -> Dict[str, Any]:
    """Standard crawler: download via aria2c, store via put_asset()."""
    from ..materializers.aria2_materializer import download_via_aria2

    return download_via_aria2(
        asset_id=asset["asset_id"],
        source_url=asset.get("source_url", ""),
        source_type=asset.get("source_type", "unknown"),
        project=project,
    )


def _get_materializer() -> Callable[[Dict[str, Any], str | None], Dict[str, Any]]:
    """Return the appropriate materializer function based on QURO_MATERIALIZER."""
    if MATERIALIZER == "aria2":
        return _materialize_via_aria2
    return _materialize_via_httpx


# ── Pipeline entry points ─────────────────────────────────────────────


def run_materialize_pipeline(doc_id: str) -> Dict[str, Any]:
    """Download all pending assets for a document.

    Reads document metadata to find pending assets, downloads each one
    via the configured materializer, and stores the result via put_asset().

    Returns a summary dict with per-asset results.
    """
    doc = read_raw_doc(doc_id)
    if doc is None:
        return {"status": "not_found", "doc_id": doc_id}

    meta = doc.get("meta", {})
    if isinstance(meta, dict):
        inner_meta = meta.get("meta", {})
        assets = (inner_meta if "assets" in inner_meta else meta).get("assets", [])
    else:
        assets = []

    if not assets:
        return {"status": "ok", "doc_id": doc_id, "results": [], "message": "no assets to materialize"}

    pending = [a for a in assets if a.get("status") == "pending"]
    if not pending:
        return {"status": "ok", "doc_id": doc_id, "results": [], "message": "all assets already materialized"}

    return _materialize_batch(doc_id, pending)


def run_materialize_pipeline_for_assets(
    doc_id: str, assets: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Download a specific list of pending assets for a document.

    Args:
        doc_id: The document ID (for logging/reference).
        assets: List of asset promise dicts to materialize.

    Returns a summary dict with per-asset results.
    """
    if not assets:
        return {"status": "ok", "doc_id": doc_id, "results": [], "message": "no assets to materialize"}

    pending = [a for a in assets if a.get("status") == "pending"]
    if not pending:
        return {"status": "ok", "doc_id": doc_id, "results": [], "message": "all assets already materialized"}

    return _materialize_batch(doc_id, pending)


def _materialize_batch(doc_id: str, pending: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Download a batch of pending assets using the configured materializer."""
    materialize = _get_materializer()

    results: List[Dict[str, Any]] = []
    downloaded = 0
    failed = 0
    skipped = 0

    for asset in pending:
        result = materialize(asset)
        results.append(result)
        if result["status"] == "downloaded":
            downloaded += 1
            print(f"  [ok] {asset['asset_id']} <- {asset.get('source_url', '')[:80]}", file=sys.stderr)
        elif result["status"] == "failed":
            failed += 1
            print(f"  [fail] {asset['asset_id']}: {result.get('error', 'unknown')}", file=sys.stderr)
        else:
            skipped += 1

    return {
        "status": "ok",
        "doc_id": doc_id,
        "materializer": MATERIALIZER,
        "downloaded": downloaded,
        "failed": failed,
        "skipped": skipped,
        "total": len(pending),
        "results": results,
    }
