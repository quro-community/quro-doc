"""CrawlerProtocol — structural contract for writer↔crawler communication.

Defines the only channel through which the Writer can learn about asset readiness.
TDA role: Policy (declarative interface, no implementation).
"""

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class AssetReadiness:
    """Asset readiness state at the protocol boundary.

    Fields:
        asset_id:  The asset identifier.
        status:    Current state — "ready", "pending", or "failed".
        file_path: Local file path (populated when ready).
        mime_type: MIME type (populated when ready).
        size_bytes: File size in bytes (populated when ready).
        error:     Error message (populated when failed).
    """

    asset_id: str
    status: str  # "ready" | "pending" | "failed"
    file_path: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    error: str | None = None


class CrawlerProtocol(Protocol):
    """Structural protocol for writer↔crawler communication.

    Any object with is_ready() and on_asset_ready() satisfies this contract.
    TDA role: Policy.
    """

    def is_ready(self, asset_id: str, source_url: str) -> AssetReadiness:
        """Synchronous poll: returns current readiness state for a single asset.

        Must return immediately. No blocking I/O.
        source_url is the original URL from the asset promise.
        status="ready" requires file_path, mime_type, size_bytes to be populated.
        status="failed" requires error to be populated.
        """
        ...

    def on_asset_ready(
        self, asset_id: str, source_url: str, callback: Callable[[AssetReadiness], None]
    ) -> None:
        """Register a callback to be invoked when the asset becomes ready.

        source_url is the original URL from the asset promise.
        If already ready, may invoke callback immediately.
        Callback is invoked at most once.
        Non-blocking registration.
        """
        ...
