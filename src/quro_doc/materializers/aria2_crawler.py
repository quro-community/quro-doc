"""Aria2Crawler — standard crawler using aria2 daemon + JSON-RPC.

Fires ready signal on download-start events as "link reachable" confirmation.
Inlines Aria2Rpc patterns from tmp/aria2_rpc_download.py. No external deps.
TDA role: Extension.
"""

import json
import os
import random
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

from ..protocols.crawler import AssetReadiness, CrawlerProtocol

_ARIA2_CONF = os.environ.get(
    "ARIA2_CONF_PATH", os.path.expanduser("~/.aria2/aria2.conf")
)
_ALL_PROXY = os.environ.get("ALL_PROXY", "http://127.0.0.1:7890")


class Aria2RpcError(Exception):
    pass


class Aria2Rpc:
    """JSON-RPC client for aria2 (stdlib only, no deps)."""

    def __init__(self, port: int) -> None:
        self._endpoint = f"http://127.0.0.1:{port}/jsonrpc"
        self._id = 0

    def _call(self, method: str, params: list | None = None) -> dict:
        self._id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": str(self._id),
            "method": method,
            "params": params or [],
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self._endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError) as e:
            raise Aria2RpcError(f"RPC call failed: {e}")
        if "error" in result:
            raise Aria2RpcError(
                f"RPC error [code={result['error']['code']}]: "
                f"{result['error'].get('message', '')}"
            )
        return result.get("result", {})

    def add_uri(self, uri: str, options: dict | None = None) -> str:
        return self._call("aria2.addUri", [[uri], options or {}])

    def tell_status(self, gid: str) -> dict:
        return self._call("aria2.tellStatus", [gid])

    def tell_active(self) -> list[dict]:
        return self._call("aria2.tellActive") or []

    def remove(self, gid: str) -> str | None:
        try:
            return self._call("aria2.remove", [gid])
        except Aria2RpcError:
            return None

    def remove_result(self, gid: str) -> None:
        try:
            self._call("aria2.removeDownloadResult", [gid])
        except Aria2RpcError:
            pass

    def purge_result(self, gid: str) -> None:
        self.remove(gid)
        self.remove_result(gid)

    def shutdown(self) -> None:
        try:
            self._call("aria2.shutdown")
        except Exception:
            pass

    def get_version(self) -> dict:
        return self._call("aria2.getVersion")


class Aria2Crawler:
    """aria2-based crawler. Implements CrawlerProtocol structurally.

    Manages aria2 daemon lifecycle. Fires ready signals on download-start events.
    TDA role: Extension.
    """

    def __init__(self) -> None:
        self._rpc: Aria2Rpc | None = None
        self._ready_states: dict[str, AssetReadiness] = {}
        self._callbacks: dict[str, list[Callable[[AssetReadiness], None]]] = {}
        self._gid_map: dict[str, str] = {}
        self._reverse_gid_map: dict[str, str] = {}
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None

        self._setup_signals()
        port = self._start_daemon()
        self._rpc = self._wait_for_rpc(port)
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _setup_signals(self) -> None:
        def handler(sig, frame):
            self._shutdown()

        try:
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
        except ValueError:
            pass

    def is_ready(self, asset_id: str, source_url: str) -> AssetReadiness:
        if asset_id in self._ready_states:
            return self._ready_states[asset_id]
        return AssetReadiness(asset_id=asset_id, status="pending")

    def on_asset_ready(
        self,
        asset_id: str,
        source_url: str,
        callback: Callable[[AssetReadiness], None],
    ) -> None:
        gid = self._rpc.add_uri(source_url)
        self._gid_map[asset_id] = gid
        self._reverse_gid_map[gid] = asset_id
        if asset_id not in self._callbacks:
            self._callbacks[asset_id] = []
        self._callbacks[asset_id].append(callback)

    def _start_daemon(self) -> int:
        for _attempt in range(10):
            port = random.randint(12000, 32000)
            cmd = [
                "aria2c",
                f"--conf-path={_ARIA2_CONF}",
                f"--all-proxy={_ALL_PROXY}",
                "--enable-rpc",
                f"--rpc-listen-port={port}",
                "--rpc-allow-origin-all",
                "--disable-ipv6",
                "--daemon",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if "port" not in result.stderr.lower():
                return port
            if "already in use" in result.stderr:
                continue
            raise RuntimeError(
                f"aria2 daemon failed to start:\n{result.stderr[:500]}"
            )
        raise RuntimeError(
            "Could not find free port for aria2 RPC after 10 attempts"
        )

    def _wait_for_rpc(self, port: int, timeout: float = 30.0) -> Aria2Rpc:
        rpc = Aria2Rpc(port)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                rpc.get_version()
                return rpc
            except Aria2RpcError:
                time.sleep(0.5)
        raise RuntimeError(
            f"aria2 RPC not responding on port {port} after {timeout}s"
        )

    def _poll_loop(self) -> None:
        while not self._poll_stop.is_set():
            if self._rpc is None:
                break
            pending = dict(self._gid_map)
            for asset_id, gid in pending.items():
                if asset_id in self._ready_states:
                    continue
                try:
                    status = self._rpc.tell_status(gid)
                    st = status.get("status", "")
                    if st == "active":
                        self._ready_states[asset_id] = AssetReadiness(
                            asset_id=asset_id,
                            status="ready",
                        )
                        self._fire_callbacks(asset_id)
                        self._rpc.purge_result(gid)
                    elif st == "error":
                        err_code = status.get("errorCode", "")
                        err_msg = status.get("errorMessage", "unknown")
                        self._ready_states[asset_id] = AssetReadiness(
                            asset_id=asset_id,
                            status="failed",
                            error=f"aria2 [{err_code}]: {err_msg}",
                        )
                        self._fire_callbacks(asset_id)
                        self._rpc.purge_result(gid)
                    elif st in ("complete", "removed"):
                        if asset_id not in self._ready_states:
                            self._ready_states[asset_id] = AssetReadiness(
                                asset_id=asset_id,
                                status="ready",
                            )
                            self._fire_callbacks(asset_id)
                except Aria2RpcError:
                    pass
            self._poll_stop.wait(0.5)

    def _fire_callbacks(self, asset_id: str) -> None:
        readiness = self._ready_states[asset_id]
        for cb in self._callbacks.pop(asset_id, []):
            try:
                cb(readiness)
            except Exception:
                pass

    def _shutdown(self) -> None:
        self._poll_stop.set()
        if self._rpc is not None:
            try:
                self._rpc.shutdown()
            except Exception:
                pass
        self._rpc = None
