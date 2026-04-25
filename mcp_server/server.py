"""ShopAI MCP server stdio transport — Wave B-2 A5.

Model Context Protocol servers communicate over a line-based
JSON-RPC 2.0 wire. Claude Desktop / Claude Code / Cursor
launch the server as a subprocess and speak:

    → {"jsonrpc":"2.0","id":1,"method":"initialize",...}
    ← {"jsonrpc":"2.0","id":1,"result":{...}}
    → {"jsonrpc":"2.0","id":2,"method":"tools/list"}
    ← {"jsonrpc":"2.0","id":2,"result":{"tools":[...]}}
    → {"jsonrpc":"2.0","id":3,"method":"tools/call",
       "params":{"name":"brain_snapshot","arguments":{}}}
    ← {"jsonrpc":"2.0","id":3,"result":{"content":[...]}}

This module owns the framing only — it imports
``build_default_registry`` from ``mcp_server.tools`` and routes
``tools/list`` and ``tools/call`` into it. Writes are gated to
stderr so MCP hosts don't try to parse log lines as protocol.

Usage (Claude Desktop ``claude_desktop_config.json``):

    {
      "mcpServers": {
        "shopai": {
          "command": "python",
          "args": ["-m", "mcp_server.server"],
          "env": {"PYTHONPATH": "/path/to/shopai"}
        }
      }
    }

Pure stdlib. Dependency-injectable stdin / stdout so tests run
offline against io.StringIO.
"""
from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass
from typing import Any, IO, Optional

from mcp_server.tools import (
    ToolCall,
    ToolRegistry,
    build_default_registry,
)


_PROTOCOL_VERSION = "2024-11-05"
_SERVER_NAME = "shopai"
_SERVER_VERSION = "1.0.0"


@dataclass
class _JsonRpcRequest:
    id: Any
    method: str
    params: dict[str, Any]


class ProtocolError(Exception):
    """Raised when an incoming message violates JSON-RPC."""


def _parse_request(line: str) -> _JsonRpcRequest | None:
    """Parse one line into a JSON-RPC request, or return None for
    notifications (no id). Raises ProtocolError on malformed JSON."""
    s = line.strip()
    if not s:
        return None
    try:
        msg = json.loads(s)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid json: {exc}") from exc
    if not isinstance(msg, dict):
        raise ProtocolError("message must be a json object")
    if msg.get("jsonrpc") != "2.0":
        raise ProtocolError("jsonrpc must be '2.0'")
    method = msg.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolError("method required")
    rid = msg.get("id")
    # Notifications have no id and expect no response
    if rid is None and "id" not in msg:
        return None
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    return _JsonRpcRequest(
        id=rid, method=method, params=params,
    )


def _ok(rid: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(
    rid: Any, code: int, message: str,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": rid,
        "error": {"code": code, "message": message},
    }


class StdioServer:
    """JSON-RPC stdio framing over a ToolRegistry.

    Line-delimited — one JSON object per line. Consistent with
    Claude Desktop's ndjson stdio transport for MCP servers.
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        stdin: Optional[IO[str]] = None,
        stdout: Optional[IO[str]] = None,
        stderr: Optional[IO[str]] = None,
    ) -> None:
        self._registry = registry or build_default_registry()
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._lock = threading.Lock()
        self._stopped = False

    # ── One-shot request dispatch (used by tests + loop) ──

    def handle_message(
        self, line: str,
    ) -> dict[str, Any] | None:
        """Parse + dispatch a single raw line. Returns the
        response dict (or None for notifications / blank)."""
        try:
            req = _parse_request(line)
        except ProtocolError as exc:
            return _err(None, -32700, str(exc))
        if req is None:
            return None
        return self._dispatch(req)

    def _dispatch(
        self, req: _JsonRpcRequest,
    ) -> dict[str, Any]:
        method = req.method
        if method == "initialize":
            return _ok(req.id, {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": _SERVER_NAME,
                    "version": _SERVER_VERSION,
                },
            })
        if method in ("ping",):
            return _ok(req.id, {})
        if method == "tools/list":
            tools = [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "inputSchema": spec.input_schema,
                }
                for spec in self._registry.list_tools()
            ]
            return _ok(req.id, {"tools": tools})
        if method == "tools/call":
            name = str(req.params.get("name", ""))
            args = req.params.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}
            if not name:
                return _err(
                    req.id, -32602,
                    "tools/call requires name",
                )
            call = ToolCall(
                tool=name,
                arguments=args,
                request_id=str(req.id),
            )
            result = self._registry.call(call)
            return _ok(req.id, result.to_mcp())
        return _err(
            req.id, -32601,
            f"method not found: {method}",
        )

    # ── Output framing ────────────────────────────────────

    def _write(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, separators=(",", ":"))
        with self._lock:
            self._stdout.write(line + "\n")
            self._stdout.flush()

    def _log(self, msg: str) -> None:
        try:
            self._stderr.write(f"[shopai-mcp] {msg}\n")
            self._stderr.flush()
        except Exception:  # noqa: BLE001
            pass

    # ── Loop ──────────────────────────────────────────────

    def stop(self) -> None:
        self._stopped = True

    def serve_forever(self) -> None:
        """Blocking read loop. One JSON object per line until
        EOF or ``stop()``. Errors on individual lines do NOT
        bring the server down — they emit a JSON-RPC error
        response and continue, matching MCP host expectations.
        """
        self._log(
            f"starting; tools={len(self._registry.list_tools())}",
        )
        while not self._stopped:
            line = self._stdin.readline()
            if not line:
                break
            resp = self.handle_message(line)
            if resp is not None:
                self._write(resp)
        self._log("stopped")


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m mcp_server.server``."""
    server = StdioServer()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
