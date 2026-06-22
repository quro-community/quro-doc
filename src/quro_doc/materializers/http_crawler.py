"""HttpCrawler — lightweight HTTP reachability check via httpx HEAD requests.

Implements CrawlerProtocol structurally. MVP fast-path for CI/dev.
TDA role: Extension.
"""

import httpx
from typing import Callable

from ..protocols.crawler import AssetReadiness, CrawlerProtocol


class HttpCrawler:
    """HTTP reachability check. Implements CrawlerProtocol structurally.

    Uses httpx for HEAD requests. No daemon. No async notification.
    TDA role: Extension.
    """

    def __init__(self, timeout: float = 1.0) -> None:
        self._timeout = timeout

    def is_ready(self, asset_id: str, source_url: str) -> AssetReadiness:
        """HEAD request to source_url. Returns AssetReadiness with status
        based on HTTP response.

        - 2xx/3xx -> ready
        - timeout/network error -> pending
        - 4xx/5xx -> failed
        """
        try:
            resp = httpx.head(
                source_url,
                timeout=self._timeout,
                follow_redirects=True,
            )
            if resp.status_code < 400:
                content_type = resp.headers.get("content-type", "")
                content_length_raw = resp.headers.get("content-length")
                size_bytes = None
                if content_length_raw is not None:
                    try:
                        size_bytes = int(content_length_raw)
                    except ValueError:
                        pass
                return AssetReadiness(
                    asset_id=asset_id,
                    status="ready",
                    file_path=source_url,
                    mime_type=content_type or None,
                    size_bytes=size_bytes,
                )
            else:
                return AssetReadiness(
                    asset_id=asset_id,
                    status="failed",
                    error=f"HTTP {resp.status_code}",
                )
        except httpx.TimeoutException:
            return AssetReadiness(asset_id=asset_id, status="pending")
        except Exception as e:
            return AssetReadiness(
                asset_id=asset_id,
                status="pending",
                error=str(e),
            )

    def on_asset_ready(
        self,
        asset_id: str,
        source_url: str,
        callback: Callable[[AssetReadiness], None],
    ) -> None:
        """No-op. HttpCrawler has no async notification mechanism."""
        pass
