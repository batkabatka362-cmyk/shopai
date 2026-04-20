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

__all__ = [
    "ToolCall",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "build_default_registry",
]
