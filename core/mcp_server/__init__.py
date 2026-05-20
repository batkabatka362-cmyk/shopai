"""ShopAI Model Context Protocol (MCP) server.

Exposes ShopAI's autonomous-merchant capabilities as MCP
tools so Claude Desktop / Claude.ai users can drive the
autonomous launch directly from a Claude conversation.

Architecture:

  Claude Desktop / Claude.ai
        │
        │ (MCP protocol via stdio / SSE)
        ▼
  ``core.mcp_server.server.build_server()``
        │
        │ registers tools defined in ``tools.py``
        ▼
  Tool function wraps existing engine layer
        │
        │ (recommend_homepage_hero,
        │  audit_launch_readiness, etc.)
        ▼
  ShopAI engines + 130+ Shopify adapters

The MCP wrapper is intentionally thin -- it serialises
calls + arguments + returns. All the autonomous-merchant
logic lives in the existing engine layer (``engines/``)
and adapter layer (``core/adapters/shopify/``).

Why this matters:

  Anthropic's official Claude × Shopify connector is
  primarily READ-oriented (search_products, get_order,
  list_customers). It turns the Shopify admin into a
  chat interface.

  ShopAI's MCP server is WRITE-oriented: launch a store,
  generate niche-aware homepage hero / theme palette /
  email sequences / customer segments, audit launch
  readiness, etc. Different layer of the stack.

Run:

  python -m core.mcp_server.server

Or wire as a Claude Desktop custom MCP server:

  {
    "mcpServers": {
      "shopai": {
        "command": "python",
        "args": ["-m", "core.mcp_server.server"]
      }
    }
  }
"""
from __future__ import annotations

from .server import build_server  # noqa: F401
from .tools import REGISTERED_TOOLS  # noqa: F401
