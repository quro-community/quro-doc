"""OKF Frontmatter Parser — parse YAML frontmatter and extract markdown internal links.

Pure function. No I/O. No side effects. No quro-doc dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

# Match YAML frontmatter between --- delimiters
_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*\n", re.DOTALL)

# Match markdown internal links: [text](path/to/file.md)
# Captures text and the path part
_INTERNAL_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+\.md)\)")

# OKF frontmatter fields that are parsed and mapped
_OKF_FIELDS = {"type", "title", "description", "resource", "tags", "timestamp"}


@dataclass
class ParsedConcept:
    """Result of parsing a single OKF concept file."""

    frontmatter: dict
    body: str
    internal_links: list[str] = field(default_factory=list)
    doc_id: str = ""
    raw_frontmatter: str = ""


def _extract_frontmatter(content: str) -> tuple[str, dict, str]:
    """Extract YAML frontmatter and body from raw file content.

    Returns:
        (body_without_frontmatter, frontmatter_dict, raw_yaml_string)
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return content, {}, ""

    yaml_str = match.group(1)
    body = content[match.end():]

    try:
        frontmatter = yaml.safe_load(yaml_str) or {}
    except yaml.YAMLError:
        return body, {}, yaml_str

    if not isinstance(frontmatter, dict):
        return body, {}, yaml_str

    return body, frontmatter, yaml_str


def _extract_internal_links(content: str) -> list[str]:
    """Extract internal markdown links from content.

    Matches patterns like [text](/path/to/concept.md) and [text](./other.md).
    Returns list of link targets (the path part).
    """
    links = []
    for match in _INTERNAL_LINK_RE.finditer(content):
        target = match.group(2)
        links.append(target)
    return links


def _derive_doc_id(relative_path: str) -> str:
    """Derive doc_id from the file's relative path, stripping .md suffix.

    The doc_id preserves the directory structure of the bundle.
    """
    if relative_path.endswith(".md"):
        relative_path = relative_path[:-3]
    return relative_path


def parse_frontmatter(raw_content: str, relative_path: str) -> ParsedConcept:
    """Parse YAML frontmatter and extract internal links from an OKF concept file.

    Pure function. No I/O. No side effects.
    Tolerates missing `type` frontmatter field.
    Body is returned unchanged.

    Args:
        raw_content: The full file content as a string.
        relative_path: The file's path relative to the bundle root.

    Returns:
        ParsedConcept with frontmatter dict, body, internal_links list, and doc_id.
    """
    body, frontmatter, raw_yaml = _extract_frontmatter(raw_content)
    internal_links = _extract_internal_links(body)

    doc_id = _derive_doc_id(relative_path)

    return ParsedConcept(
        frontmatter=frontmatter,
        body=body,
        internal_links=internal_links,
        doc_id=doc_id,
        raw_frontmatter=raw_yaml,
    )
