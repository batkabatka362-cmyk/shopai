"""ShopAI MCP server -- main entry point.

Boots a Model Context Protocol server that exposes the
tools defined in ``tools.py`` to a connected MCP client
(Claude Desktop, Claude.ai web with Custom Connectors,
or any other MCP-compatible client).

Run modes:

  python -m core.mcp_server.server         # stdio transport
  python -m core.mcp_server.server --sse   # SSE transport

Stdio is the default for local Claude Desktop integration.
SSE is for HTTP-style clients.

The ``mcp`` Python SDK is an OPTIONAL dependency. Install
via ``pip install mcp`` if you actually want to run the
server. Without it the module still imports cleanly and
``build_server()`` raises a friendly error at call time.

Why lazy: keeps the autonomous-merchant engine path
deployable without forcing every test environment to pull
the mcp package.
"""
from __future__ import annotations

import inspect
import logging
import sys
from typing import Any

from .tools import REGISTERED_TOOLS, ToolFn

logger = logging.getLogger(__name__)


_SERVER_NAME: str = "shopai"
_SERVER_VERSION: str = "0.1.0"


def build_server() -> Any:
    """Construct an MCP server with all ShopAI tools
    registered.

    Returns:
        The mcp.server.FastMCP instance. Caller invokes
        ``server.run()`` to start the event loop.

    Raises:
        RuntimeError: if the ``mcp`` package isn't
            installed in the current Python environment.
    """
    try:
        # mcp 0.9+ exposes FastMCP for the simple
        # decorator-based registration pattern.
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "mcp package not installed. "
            "Install with `pip install mcp` to run the "
            f"ShopAI MCP server. (import error: {exc})"
        ) from exc

    server = FastMCP(_SERVER_NAME)

    for tool_name, fn, description in REGISTERED_TOOLS:
        _register_tool(server, tool_name, fn, description)

    logger.info(
        "shopai_mcp_server: registered %d tools",
        len(REGISTERED_TOOLS),
    )
    return server


def _register_tool(
    server: Any,
    tool_name: str,
    fn: ToolFn,
    description: str,
) -> None:
    """Register a single tool function with the MCP server.

    FastMCP infers the tool signature + JSON-Schema from
    the wrapped function's type hints. We preserve the
    original ``fn.__name__``-or-``tool_name`` distinction
    by re-binding ``__name__`` so Claude sees a friendly
    tool name (e.g. ``recommend_pages`` instead of the
    bound ``fn``).
    """
    # Create a thin wrapper to (a) rename for display and
    # (b) ensure the function is registered with the
    # description we want.
    wrapped = _make_wrapper(fn, tool_name)
    server.tool(name=tool_name, description=description)(
        wrapped,
    )


def _make_wrapper(fn: ToolFn, tool_name: str) -> ToolFn:
    """Re-bind a function under a new ``__name__`` while
    preserving its signature -- FastMCP introspects the
    wrapped function to build the tool schema."""
    # Preserve signature by re-wrapping with the same
    # parameter list.
    sig = inspect.signature(fn)

    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return fn(*args, **kwargs)

    wrapper.__name__ = tool_name
    wrapper.__qualname__ = tool_name
    wrapper.__doc__ = fn.__doc__
    wrapper.__signature__ = sig  # type: ignore[attr-defined]
    # Carry over annotations for FastMCP's schema gen
    wrapper.__annotations__ = dict(fn.__annotations__)
    return wrapper


def main() -> None:
    """Stdio entry point.

    Wire this into Claude Desktop's `claude_desktop_config.json`:

      {
        "mcpServers": {
          "shopai": {
            "command": "python",
            "args": ["-m", "core.mcp_server.server"]
          }
        }
      }
    """
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)s "
            "shopai_mcp[%(name)s] %(message)s"
        ),
    )
    try:
        server = build_server()
    except RuntimeError as exc:
        # Print to stderr so the operator sees the
        # actionable install hint without the mcp client
        # silently hanging.
        print(
            f"ShopAI MCP server failed to start: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)

    # FastMCP exposes both stdio + sse. Default is stdio
    # which matches Claude Desktop's integration model.
    server.run()


if __name__ == "__main__":
    main()
