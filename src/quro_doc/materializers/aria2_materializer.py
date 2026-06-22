"""Aria2Materializer — standard crawler using aria2c for downloads.

Uses subprocess to invoke aria2c directly (no daemon required).
Downloads to temp dir, then stores via put_asset().
TDA role: Extension.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Dict, Any

from ..storage import put_asset
from ..storage_layer import StorageLayer


def _find_aria2c() -> str | None:
    """Find the aria2c binary. Returns path or None."""
    for candidate in ("aria2c", "/usr/local/bin/aria2c", "/opt/homebrew/bin/aria2c"):
        try:
            subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                timeout=3,
            )
            return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def download_via_aria2(
    asset_id: str,
    source_url: str,
    source_type: str,
    project: str | None = None,
) -> Dict[str, Any]:
    """Download a single asset via aria2c and store it via put_asset().

    Runs aria2c in subprocess mode (--daemon=false), downloads to a temp file,
    reads the file, stores it via put_asset(), and cleans up.

    Returns {asset_id, status, ...}.
    """
    if source_type not in ("https",):
        return {
            "asset_id": asset_id,
            "status": "skipped",
            "reason": f"source_type '{source_type}' not supported",
        }

    aria2c = _find_aria2c()
    if aria2c is None:
        return {
            "asset_id": asset_id,
            "status": "failed",
            "error": "aria2c not found on PATH",
        }

    root = None
    if project:
        layer = StorageLayer()
        root = layer.resolve_storage_root(project)

    aria2_conf = os.environ.get(
        "ARIA2_CONF_PATH", os.path.expanduser("~/.aria2/aria2.conf")
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = os.path.join(tmpdir, asset_id)
        cmd = [
            aria2c,
            source_url,
            f"--dir={tmpdir}",
            f"--out={asset_id}",
            f"--conf-path={aria2_conf}",
            "--daemon=false",
            "--enable-rpc=false",
            "--check-certificate=false",
            "--max-connection-per-server=4",
            "--split=4",
            "--allow-overwrite=true",
            "--console-log-level=error",
        ]
        all_proxy = os.environ.get("ALL_PROXY")
        if all_proxy:
            cmd.append(f"--all-proxy={all_proxy}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return {
                "asset_id": asset_id,
                "status": "failed",
                "source_url": source_url,
                "error": "aria2c download timed out (120s)",
            }
        except FileNotFoundError:
            return {
                "asset_id": asset_id,
                "status": "failed",
                "source_url": source_url,
                "error": "aria2c not found",
            }

        if result.returncode != 0:
            error_msg = (result.stderr or result.stdout)[:200]
            return {
                "asset_id": asset_id,
                "status": "failed",
                "source_url": source_url,
                "error": f"aria2c exit {result.returncode}: {error_msg}",
            }

        if not os.path.isfile(out_file):
            return {
                "asset_id": asset_id,
                "status": "failed",
                "source_url": source_url,
                "error": "aria2c completed but output file not found",
            }

        try:
            with open(out_file, "rb") as fh:
                data = fh.read()
        except Exception as e:
            return {
                "asset_id": asset_id,
                "status": "failed",
                "source_url": source_url,
                "error": f"failed to read downloaded file: {e}",
            }

        if not data:
            return {
                "asset_id": asset_id,
                "status": "failed",
                "source_url": source_url,
                "error": "downloaded file is empty",
            }

        wrote = put_asset(
            asset_id=asset_id,
            data=data,
            content_type="application/octet-stream",
            root=root,
        )
        if wrote:
            return {
                "asset_id": asset_id,
                "status": "downloaded",
                "source_url": source_url,
                "size": len(data),
                "materializer": "aria2",
            }
        else:
            return {
                "asset_id": asset_id,
                "status": "skipped",
                "reason": "asset already exists",
            }
