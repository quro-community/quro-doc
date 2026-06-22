"""Parser layer — third-party library wrappers for content decomposition.

TDA role: Kernel (pure computation, no I/O, no quro-doc imports).
"""

from .markdown_parser import MarkdownMediaParser, MediaRef

__all__ = ["MarkdownMediaParser", "MediaRef"]
