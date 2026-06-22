"""AssetPromiseModel — manages asset promise lifecycle.

Delegates readiness queries to CrawlerProtocol.
Pure state machine. No file I/O. No network I/O. No quro-doc imports.
TDA role: Policy.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from ..protocols.crawler import AssetReadiness, CrawlerProtocol


@dataclass
class AssetPromise:
    """A promise that an asset (identified by source_url) will be materialized.

    Fields match imspec-mcp-extension-boundary §2.4 contract.
    """

    asset_id: str
    source_url: str
    source_type: str  # "https" | "file" | "unknown"
    media_type: str  # "image" | "link" | "unknown"
    alt: str
    status: str  # "pending" | "ready" | "failed"
    created_at: str


class AssetPromiseModel:
    """Manages asset promise lifecycle.

    Delegates readiness queries to CrawlerProtocol.
    Pure state machine. No I/O. No quro-doc imports.
    TDA role: Policy.
    """

    def __init__(self, crawler: CrawlerProtocol | None = None):
        """Initialize with optional crawler for readiness queries.

        If crawler is None, check_ready() returns status="pending" for all assets.
        """
        self._crawler: CrawlerProtocol | None = crawler
        self._promises: dict[str, AssetPromise] = {}

    def register(
        self,
        source_url: str,
        source_type: str = "unknown",
        media_type: str = "unknown",
        alt: str = "",
    ) -> AssetPromise:
        """Register a new asset promise. Returns immediately.

        Generates deterministic asset_id from source_url (SHA-256, first 24 hex chars).
        Idempotent: same source_url always returns same asset_id.
        """
        asset_id = hashlib.sha256(source_url.encode()).hexdigest()[:24]
        if asset_id in self._promises:
            return self._promises[asset_id]

        promise = AssetPromise(
            asset_id=asset_id,
            source_url=source_url,
            source_type=source_type,
            media_type=media_type,
            alt=alt,
            status="pending",
            created_at=datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        )
        self._promises[asset_id] = promise
        return promise

    def check_ready(self, asset_id: str) -> AssetReadiness:
        """Poll current readiness state for an asset.

        If crawler is set, delegates to crawler.is_ready(asset_id).
        If crawler is None, returns AssetReadiness(status="pending").
        Returns immediately. No blocking.
        """
        source_url = self._promises[asset_id].source_url if asset_id in self._promises else ""
        if self._crawler is not None:
            result = self._crawler.is_ready(asset_id, source_url)
        else:
            result = AssetReadiness(asset_id=asset_id, status="pending")

        if asset_id in self._promises:
            self._promises[asset_id].status = result.status

        return result

    def when_ready(
        self, asset_id: str, callback: Callable[[AssetReadiness], None]
    ) -> None:
        """Register a callback for when the asset becomes ready.

        If crawler is set, delegates to crawler.on_asset_ready().
        If crawler is None, no-op.
        Non-blocking registration.
        """
        source_url = self._promises[asset_id].source_url if asset_id in self._promises else ""
        if self._crawler is not None:
            self._crawler.on_asset_ready(asset_id, source_url, callback)

    def get_promise(self, asset_id: str) -> AssetPromise | None:
        """Retrieve a previously registered promise by asset_id."""
        return self._promises.get(asset_id)
