"""Inspect Extension — read-only metadata introspection.

Exposes operations to enumerate doc-ids, retrieve per-document metadata,
discover metadata member keys across the store, and filter documents by
metadata criteria. All operations are pure reads — zero mutations.
"""

import time
from typing import Any, Dict, List, Optional

from jsonschema import ValidationError


class BaseInspector:
    """Extension: read-only metadata introspection. TDA role: Extension."""

    def list_doc_ids(self, limit: int = 100, offset: int = 0,
                     filters: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def get_metadata(self, doc_id: str,
                     metadata_set: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def list_metadata_keys(self, min_coverage: float = 0.0,
                           metadata_set: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def query_by_metadata(self, filters: List[Dict[str, Any]],
                          limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        raise NotImplementedError


class MetadataInspector(BaseInspector):
    """Concrete inspector — delegates data access to Core (api / storage)."""

    PROTOCOL_VERSION = "1.0.0"

    def list_doc_ids(self, limit: int = 100, offset: int = 0,
                     filters: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        start = time.time()
        from ..config import QuroConfig       # no stale references
        cfg = QuroConfig.load()
        from ..storage import list_raw_docs
        docs = list_raw_docs(limit=100000, root=cfg.storage_root)

        if filters:
            docs = [d for d in docs
                    if all(self._apply_filter(d.get("meta", {}), f) for f in filters)]

        total = len(docs)
        docs.sort(key=lambda d: d.get("meta", {}).get("created_at", ""), reverse=True)
        page = docs[offset:offset + limit]
        doc_ids = [self._build_doc_summary(d) for d in page]

        return {
            "protocol_version": self.PROTOCOL_VERSION,
            "doc_ids": doc_ids,
            "total": total,
            "has_more": offset + limit < total,
            "latency_ms": (time.time() - start) * 1000,
        }

    def get_metadata(self, doc_id: str,
                     metadata_set: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        if metadata_set is not None:
            error = self._validate_metadata_set(metadata_set)
            if error:
                return error

        start = time.time()
        from ..api import quro_doc_get
        result = quro_doc_get(doc_id)
        latency_ms = (time.time() - start) * 1000

        if result.get("status") == "not_found":
            return {
                "protocol_version": self.PROTOCOL_VERSION,
                "status": "not_found",
                "doc_id": doc_id,
                "latency_ms": latency_ms,
            }

        raw_meta = result.get("meta", {})
        if isinstance(raw_meta, dict) and "meta" in raw_meta:
            inner = raw_meta["meta"]
            if isinstance(inner, dict):
                raw_meta = inner

        if metadata_set is not None and isinstance(raw_meta, dict):
            declared_keys = {item["key"] for item in metadata_set}
            filtered = {k: raw_meta[k] for k in declared_keys if k in raw_meta}
            raw_meta = filtered

        return {
            "protocol_version": self.PROTOCOL_VERSION,
            "doc_id": doc_id,
            "metadata": raw_meta,
            "latency_ms": latency_ms,
        }

    def list_metadata_keys(self, min_coverage: float = 0.0,
                           metadata_set: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        if metadata_set is not None:
            error = self._validate_metadata_set(metadata_set)
            if error:
                return error

        start = time.time()
        if metadata_set is not None:
            return self._list_declared_keys(metadata_set, min_coverage)
        keys_info, total_docs = self._scan_metadata()

        if min_coverage > 0:
            keys_info = [k for k in keys_info if k["coverage"] >= min_coverage]

        return {
            "protocol_version": self.PROTOCOL_VERSION,
            "metadata_keys": keys_info,
            "total_docs": total_docs,
            "latency_ms": (time.time() - start) * 1000,
        }

    def query_by_metadata(self, filters: List[Dict[str, Any]],
                          limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        start = time.time()
        from ..config import QuroConfig
        cfg = QuroConfig.load()
        from ..storage import list_raw_docs
        docs = list_raw_docs(limit=100000, root=cfg.storage_root)

        matched = [d for d in docs
                   if all(self._apply_filter(d.get("meta", {}), f) for f in filters)]
        total = len(matched)
        matched.sort(key=lambda d: d.get("meta", {}).get("created_at", ""), reverse=True)
        page = matched[offset:offset + limit]
        results = [self._build_doc_summary(d) for d in page]

        return {
            "protocol_version": self.PROTOCOL_VERSION,
            "results": results,
            "total": total,
            "has_more": offset + limit < total,
            "filters_applied": filters,
            "latency_ms": (time.time() - start) * 1000,
        }

    # ── internal helpers ───────────────────────────────────────────────

    def _validate_metadata_set(self, metadata_set: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        """Validate metadata_set against the Inspect Protocol schema.

        Returns None on success (caller-declared metadata_set conforms).
        Returns a protocol-violation error dict on failure with the
        specific protocol version and schema name referenced.
        """
        from ..protocols.validator import ProtocolValidator
        try:
            validator = ProtocolValidator()
            validator.validate_metadata_set(metadata_set)
        except ValidationError as e:
            errors = []
            current = e
            while current:
                errors.append(current.message)
                current = current.context[0] if current.context else None
            return {
                "status": "error",
                "message": (
                    f"metadata_set violates inspect protocol "
                    f"v{self.PROTOCOL_VERSION}: {'; '.join(errors)}"
                ),
                "error": (
                    f"metadata_set violates inspect protocol "
                    f"v{self.PROTOCOL_VERSION}: {'; '.join(errors)}"
                ),
                "protocol_version": self.PROTOCOL_VERSION,
                "protocol_violated": "metadata_set_v1",
                "validation_errors": errors,
            }
        return None

    def _list_declared_keys(self, metadata_set: List[Dict[str, str]],
                            min_coverage: float = 0.0) -> Dict[str, Any]:
        start = time.time()
        from ..config import QuroConfig
        cfg = QuroConfig.load()
        from ..storage import list_raw_docs
        docs = list_raw_docs(limit=100000, root=cfg.storage_root)
        total_docs = len(docs)

        declared_keys = [item["key"] for item in metadata_set]
        key_descs = {item["key"]: item for item in metadata_set}

        key_stats: Dict[str, Dict[str, Any]] = {k: {"doc_count": 0, "sample_values": []}
                                                  for k in declared_keys}

        for doc in docs:
            meta = doc.get("meta", {})
            if not isinstance(meta, dict):
                continue
            for key in declared_keys:
                if key in meta:
                    stats = key_stats[key]
                    stats["doc_count"] += 1
                    if len(stats["sample_values"]) < 5:
                        stats["sample_values"].append(meta[key])

        keys_info = []
        for key in declared_keys:
            stats = key_stats[key]
            coverage = stats["doc_count"] / total_docs if total_docs else 0.0
            if min_coverage > 0 and coverage < min_coverage:
                continue
            desc = key_descs[key]
            keys_info.append({
                "key": key,
                "description": desc.get("description"),
                "domain": desc.get("domain"),
                "map_to": desc.get("map_to"),
                "doc_count": stats["doc_count"],
                "total_docs": total_docs,
                "coverage": coverage,
                "sample_values": stats["sample_values"],
            })

        keys_info.sort(key=lambda k: k["doc_count"], reverse=True)
        return {
            "protocol_version": self.PROTOCOL_VERSION,
            "metadata_keys": keys_info,
            "total_docs": total_docs,
            "latency_ms": (time.time() - start) * 1000,
        }

    def _scan_metadata(self):
        from ..config import QuroConfig
        cfg = QuroConfig.load()
        from ..storage import list_raw_docs
        docs = list_raw_docs(limit=100000, root=cfg.storage_root)
        total_docs = len(docs)

        key_stats: Dict[str, Dict[str, Any]] = {}

        for doc in docs:
            meta = doc.get("meta", {})
            if not isinstance(meta, dict):
                continue
            for key, value in meta.items():
                if key not in key_stats:
                    key_stats[key] = {
                        "types": set(),
                        "doc_count": 0,
                        "sample_values": [],
                    }
                stats = key_stats[key]
                stats["doc_count"] += 1
                vt = self._infer_value_type(value)
                stats["types"].add(vt)
                if len(stats["sample_values"]) < 5:
                    stats["sample_values"].append(value)

        keys_info = []
        for key, stats in key_stats.items():
            types = stats["types"]
            value_type = "mixed" if len(types) > 1 else (next(iter(types)) if types else "null")
            keys_info.append({
                "key": key,
                "value_type": value_type,
                "doc_count": stats["doc_count"],
                "total_docs": total_docs,
                "coverage": stats["doc_count"] / total_docs if total_docs else 0.0,
                "sample_values": stats["sample_values"],
            })

        keys_info.sort(key=lambda k: k["doc_count"], reverse=True)
        return keys_info, total_docs

    @staticmethod
    def _infer_value_type(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "string"

    def _apply_filter(self, doc_meta: dict, filter_def: dict) -> bool:
        key = filter_def["key"]
        operator = filter_def["operator"]
        value = filter_def.get("value")

        field_value = doc_meta
        for part in key.split("."):
            if isinstance(field_value, dict):
                field_value = field_value.get(part)
            else:
                field_value = None
                break

        if operator == "exists":
            return field_value is not None

        if field_value is None:
            return operator == "neq"

        if operator == "eq":
            if isinstance(field_value, list) and isinstance(value, list):
                return sorted(field_value) == sorted(value)
            return field_value == value

        if operator == "neq":
            return field_value != value

        if operator == "contains":
            if isinstance(field_value, str) and isinstance(value, str):
                return value.lower() in field_value.lower()
            if isinstance(field_value, list):
                return value in field_value
            return False

        if operator == "gt":
            try:
                return float(field_value) > float(value)
            except (TypeError, ValueError):
                return False

        if operator == "gte":
            try:
                return float(field_value) >= float(value)
            except (TypeError, ValueError):
                return False

        if operator == "lt":
            try:
                return float(field_value) < float(value)
            except (TypeError, ValueError):
                return False

        if operator == "lte":
            try:
                return float(field_value) <= float(value)
            except (TypeError, ValueError):
                return False

        if operator == "in":
            if isinstance(value, list):
                return field_value in value
            return False

        return False

    @staticmethod
    def _build_doc_summary(doc: dict) -> dict:
        meta = doc.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}

        summary: Dict[str, Any] = {
            "doc_id": doc["doc_id"],
        }

        if meta.get("title") is not None:
            summary["title"] = meta["title"]
        if meta.get("topic") is not None:
            summary["topic"] = meta["topic"]
        if meta.get("classification") is not None:
            summary["classification"] = meta["classification"]
        if meta.get("summary") is not None:
            summary["summary"] = meta["summary"]
        if meta.get("path") is not None:
            summary["path"] = meta["path"]
        if meta.get("tags"):
            summary["tags"] = meta["tags"]
        if meta.get("created_at") is not None:
            summary["created_at"] = meta["created_at"]
        if meta.get("source"):
            summary["source"] = meta["source"]

        user_meta = meta.get("metadata", {})
        if isinstance(user_meta, dict) and user_meta:
            summary["metadata_keys"] = list(user_meta.keys())

        return summary
