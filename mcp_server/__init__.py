"""ShopAI MCP server — expose brain tools to Claude Desktop, Code,
Cursor, and any MCP-compatible client.

Wave B-2 of IMPLEMENTATION_PLAN_2026.
"""
from mcp_server.tools import (
    ToolCall,
    ToolError,
    ToolRegistry,
    ToolResult,
    build_default_registry,
)

try:
    from mcp_server.server import StdioServer
except Exception:  # noqa: BLE001
    StdioServer = None  # type: ignore[assignment]

__all__ = [
    "ToolCall",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "StdioServer",
    "build_default_registry",
]
