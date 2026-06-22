"""Reader extension — resolve asset references in retrieved documents.

Phase 1: PlainTextReader — passthrough, asset:// remains as-is.
Phase 3: MarkdownReader — resolves asset:// placeholders to local disk paths.
"""

from __future__ import annotations

import os
import re
from typing import Dict, Any

from ..storage import get_storage_root
from ..protocols.validator import ProtocolValidator
from jsonschema import ValidationError

_ASSET_URL_RE = re.compile(r"asset://([a-f0-9]{24})")


def _resolve_asset_urls(body: str) -> str:
    """Replace asset://{id} placeholders with local filesystem paths.

    Only resolves references whose assets exist on disk (downloaded).
    Unresolved asset:// refs are left as-is.
    """
    root = get_storage_root()

    def _replacer(match: re.Match) -> str:
        asset_id = match.group(1)
        asset_path = os.path.join(root, "assets", asset_id)
        if os.path.isfile(asset_path):
            return asset_path
        return match.group(0)

    return _ASSET_URL_RE.sub(_replacer, body)


class BaseReader:
    """Extension: resolve asset references in retrieved documents. TDA role: Extension/SINK."""

    def get(self, doc_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def search(self, query: Dict[str, Any]) -> Any:
        raise NotImplementedError

    def delete_asset(self, asset_id: str) -> Dict[str, Any]:
        raise NotImplementedError


class MarkdownReader(BaseReader):
    """Phase 3 resolution: resolves asset:// → local filesystem paths.

    Replaces asset://{asset_id} with the absolute path to the downloaded
    asset file on disk. Only resolved if the asset file exists locally.
    """

    def get(self, doc_id: str) -> Dict[str, Any]:
        from ..api import quro_doc_get

        result = quro_doc_get(doc_id)
        if result.get("status") == "not_found":
            return result

        body = result.get("body", "")
        if body:
            result["body"] = _resolve_asset_urls(body)

        return result

    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        from ..api import quro_doc_get_asset
        return quro_doc_get_asset(asset_id)

    def search(self, query: Dict[str, Any]) -> Any:
        from ..api import quro_doc_search
        results = quro_doc_search(query)
        if isinstance(results, list):
            try:
                validator = ProtocolValidator()
                validator.validate_output(results, "2.0")
            except ValidationError:
                pass
        return results

    def delete_asset(self, asset_id: str) -> Dict[str, Any]:
        from ..api import quro_doc_delete_asset
        return quro_doc_delete_asset(asset_id)


class PlainTextReader(BaseReader):
    """Phase 1 passthrough: delegates to Core api with no asset resolution.

    asset:// placeholders are preserved as-is in the returned body.
    Suitable for MCP tools, logs, code snippets, and plain-text formats.
    """

    def get(self, doc_id: str) -> Dict[str, Any]:
        from ..api import quro_doc_get
        return quro_doc_get(doc_id)

    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        from ..api import quro_doc_get_asset
        return quro_doc_get_asset(asset_id)

    def search(self, query: Dict[str, Any]) -> Any:
        from ..api import quro_doc_search
        results = quro_doc_search(query)
        if isinstance(results, list):
            try:
                validator = ProtocolValidator()
                validator.validate_output(results, "2.0")
            except ValidationError:
                pass
        return results

    def delete_asset(self, asset_id: str) -> Dict[str, Any]:
        from ..api import quro_doc_delete_asset
        return quro_doc_delete_asset(asset_id)
