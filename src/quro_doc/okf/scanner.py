"""OKF Bundle Scanner — walk an OKF bundle directory tree, enumerate .md concept files.

Pure file system reader. No side effects. No quro-doc dependencies.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator

SKIP_FILES = {"index.md", "log.md"}


@dataclass
class BundleEntry:
    """A single OKF concept file entry from the bundle directory."""

    relative_path: str
    raw_content: str


def _is_okf_concept(fname: str) -> bool:
    """Check if a file is an OKF concept markdown file.

    Must be a .md file and not in the skip list.
    """
    if not fname.endswith(".md"):
        return False
    return fname not in SKIP_FILES


def scan_bundle(bundle_path: str) -> Iterator[BundleEntry]:
    """Walk bundle directory, yield concept .md files.

    Skips index.md and log.md per OKF spec.
    Pure file reader — no quro-doc dependencies, no side effects.

    Args:
        bundle_path: Root directory of the OKF bundle.

    Yields:
        BundleEntry with relative_path (from bundle root) and raw_content.
    """
    abs_root = os.path.abspath(bundle_path)

    if not os.path.isdir(abs_root):
        raise NotADirectoryError(f"Bundle path is not a directory: {abs_root}")

    for dirpath, _dirnames, filenames in os.walk(abs_root):
        for fname in sorted(filenames):
            if not _is_okf_concept(fname):
                continue

            full_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(full_path, abs_root)

            try:
                with open(full_path, "r", encoding="utf-8") as fh:
                    content = fh.read()
            except (UnicodeDecodeError, PermissionError):
                continue

            if not content.strip():
                continue

            yield BundleEntry(relative_path=rel_path, raw_content=content)
