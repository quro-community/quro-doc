"""Protocol layer — structural interfaces (PEP 544) for cross-module contracts."""

from .crawler import CrawlerProtocol, AssetReadiness

__all__ = ["CrawlerProtocol", "AssetReadiness"]
