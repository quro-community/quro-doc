"""Extension layer — Reader/Writer/Inspector abstraction between MCP/CLI frontends and Core.

Exports:
    BaseReader, MarkdownReader, PlainTextReader — document retrieval
    BaseWriter, MarkdownWriter, PlainTextWriter — document creation
    BaseInspector, MetadataInspector        — metadata introspection
"""

from .reader import BaseReader, MarkdownReader, PlainTextReader
from .writer import BaseWriter, MarkdownWriter, PlainTextWriter
from .inspector import BaseInspector, MetadataInspector

__all__ = [
    "BaseReader", "MarkdownReader", "PlainTextReader",
    "BaseWriter", "MarkdownWriter", "PlainTextWriter",
    "BaseInspector", "MetadataInspector",
]
