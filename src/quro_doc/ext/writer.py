"""Writer extension — decompose rich content into body + asset promises before storage.

Phase 1: Passthrough — delegates to Core api with no content decomposition.
Phase 3: Asset-aware — extracts media URLs, registers asset promises,
         rewrites URLs to asset:// placeholders, enqueues materialize jobs.

MCP tool surface: only `file_path` is accepted for body input.
`body` is supported for programmatic/internal callers (OKF ingest, batch pipelines).
"""

from typing import Dict, Any, List
import os
from pathlib import Path

from ..parsers.markdown_parser import MarkdownMediaParser
from ..helpers.asset_promise import AssetPromiseModel


class BaseWriter:
    """Extension: parse rich content into body + asset promises before storage. TDA role: Extension."""

    def add(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def put_asset(self, asset_id: str, file_path: str,
                  mime_type: str = "application/octet-stream") -> Dict[str, Any]:
        raise NotImplementedError

    def _read_file(self, file_path: str) -> str | Dict[str, str]:
        """Read UTF-8 text file. Returns content string or error dict."""
        if not os.path.isfile(file_path):
            return {"status": "error", "message": f"file_path not found: {file_path}"}
        if os.path.isdir(file_path):
            return {"status": "error", "message": f"file_path is a directory: {file_path}"}
        if not os.access(file_path, os.R_OK):
            return {"status": "error", "message": f"file_path not readable: {file_path}"}
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                content = fh.read()
        except UnicodeDecodeError:
            return {"status": "error", "message": f"file_path is not valid UTF-8: {file_path}"}
        except Exception as e:
            return {"status": "error", "message": f"file_path read failed: {file_path} — {e}"}
        if not content:
            return {"status": "error", "message": f"file_path is empty: {file_path}"}
        return content

    def _read_file_bytes(self, file_path: str) -> bytes | Dict[str, str]:
        """Read binary file. Returns bytes or error dict."""
        if not os.path.isfile(file_path):
            return {"status": "error", "message": f"file_path not found: {file_path}"}
        if not os.access(file_path, os.R_OK):
            return {"status": "error", "message": f"file_path not readable: {file_path}"}
        try:
            with open(file_path, "rb") as fh:
                return fh.read()
        except Exception as e:
            return {"status": "error", "message": f"file_path read failed: {file_path} — {e}"}


class MarkdownWriter(BaseWriter):
    """Phase 3 asset-aware writer for rich content (Markdown).

    Delegates media extraction to MarkdownMediaParser (mistune).
    Delegates asset promise lifecycle to AssetPromiseModel.
    Never implements asset-aware logic directly.

    file_path takes precedence over body. Writer reads the file content.
    MCP tool surface exposes only file_path; body is for internal/programmatic callers.
    """

    def __init__(self,
                 promise_model: AssetPromiseModel | None = None,
                 parser: MarkdownMediaParser | None = None):
        self._promise_model = promise_model or AssetPromiseModel()
        self._parser = parser or MarkdownMediaParser()

    def add(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Add document via quro_doc_add after media extraction and URL rewriting.

        Contract:
          1. Reads content from file_path (takes precedence) or body.
          2. parser.extract(body) -> list[MediaRef].
          3. For each MediaRef: registers promise, checks readiness,
             rewrites URL to asset:// if not ready.
          4. Builds assets list from promises.
          5. Calls quro_doc_add.
          6. Synchronous only. No asset downloads.
          7. Idempotent: passes doc_id through to Core.
        """
        file_path = payload.get("file_path")
        if file_path:
            content = self._read_file(file_path)
            if isinstance(content, dict) and content.get("status") == "error":
                return content
            payload = dict(payload)
            payload.pop("file_path", None)
            payload["body"] = content
        else:
            payload = dict(payload)

        body = payload.get("body", "")

        if body:
            refs = self._parser.extract(body)
            if refs:
                resolved_promises: List[dict] = []
                for ref in reversed(refs):
                    source_type = _determine_source_type(ref.url)
                    promise = self._promise_model.register(
                        source_url=ref.url,
                        source_type=source_type,
                        media_type=ref.media_type,
                        alt=ref.alt,
                    )
                    readiness = self._promise_model.check_ready(promise.asset_id)
                    resolved_promises.append({
                        "asset_id": promise.asset_id,
                        "source_url": promise.source_url,
                        "source_type": promise.source_type,
                        "media_type": promise.media_type,
                        "alt": promise.alt,
                        "status": promise.status,
                        "created_at": promise.created_at,
                    })
                    if readiness.status != "ready":
                        url_pos = body.find(ref.url, ref.start_pos)
                        if url_pos >= ref.start_pos and url_pos < ref.end_pos:
                            asset_url = f"asset://{promise.asset_id}"
                            body = (
                                body[:url_pos]
                                + asset_url
                                + body[url_pos + len(ref.url):]
                            )

                payload["body"] = body
                existing = payload.get("assets", [])
                payload["assets"] = existing + resolved_promises

        from ..api import quro_doc_add
        return quro_doc_add(payload)

    def put_asset(self, asset_id: str, file_path: str,
                  mime_type: str = "application/octet-stream") -> Dict[str, Any]:
        data = self._read_file_bytes(file_path)
        if isinstance(data, dict) and data.get("status") == "error":
            return data
        from ..api import quro_doc_put_asset
        return quro_doc_put_asset(asset_id=asset_id, data=data, content_type=mime_type)


def _determine_source_type(url: str) -> str:
    """Classify a URL's source type for AssetPromise.source_type."""
    if url.startswith(("http://", "https://")):
        return "https"
    if url.startswith("file://"):
        return "file"
    if not url.startswith(("http://", "https://", "asset://", "data:")):
        return "file"
    return "unknown"


class PlainTextWriter(BaseWriter):
    """Phase 1 passthrough: plain-text writer for simple text content.

    Unlike MarkdownWriter, plain text has no embedded media to extract.
    No Phase 3 asset-awareness needed — always a pure passthrough.
    Suitable for logs, code snippets, config files, and other plain-text formats.

    file_path takes precedence over body. Writer reads the file content.
    """

    def add(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        file_path = payload.get("file_path")
        if file_path:
            content = self._read_file(file_path)
            if isinstance(content, dict) and content.get("status") == "error":
                return content
            payload = dict(payload)
            payload.pop("file_path", None)
            payload["body"] = content

        from ..api import quro_doc_add
        return quro_doc_add(payload)

    def put_asset(self, asset_id: str, file_path: str,
                  mime_type: str = "application/octet-stream") -> Dict[str, Any]:
        data = self._read_file_bytes(file_path)
        if isinstance(data, dict) and data.get("status") == "error":
            return data
        from ..api import quro_doc_put_asset
        return quro_doc_put_asset(asset_id=asset_id, data=data, content_type=mime_type)
