"""Adapter between Quro raw documents and Haystack Documents.

Important: Haystack Document MUST NOT be the core model.
This adapter is only used when ENABLE_HAYSTACK is true and haystack is installed.
"""

from typing import Dict, Any
import os

ENABLE_HAYSTACK = os.getenv("ENABLE_HAYSTACK", "true").lower() in ("1", "true", "yes")

try:
    if ENABLE_HAYSTACK:
        from haystack import Document as HaystackDocument  # type: ignore
    else:
        HaystackDocument = None
except Exception:
    HaystackDocument = None

def to_haystack(raw_doc: Dict[str, Any]):
    """Convert raw_doc dict -> haystack.Document (or dict fallback)"""
    if HaystackDocument:
        return HaystackDocument(content=raw_doc.get("body", ""), meta={k: v for k, v in raw_doc.items() if k != "body"})
    # fallback dict
    return {"content": raw_doc.get("body", ""), "meta": {k: v for k, v in raw_doc.items() if k != "body"}}

def from_haystack(hay_doc: Any) -> Dict[str, Any]:
    """Convert haystack Document (or fallback dict) -> quro raw representation"""
    if HaystackDocument and isinstance(hay_doc, HaystackDocument):
        return {"body": hay_doc.content, **(hay_doc.meta or {})}
    # assume dict
    return {"body": hay_doc.get("content", ""), **(hay_doc.get("meta", {}) or {})}