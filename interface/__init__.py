"""interface/ — facade for outside-world surfaces.

Per docs/FOLDER_REORG_PLAN.md Phase 2. Groups CLI, MCP server,
HTTP API, and owner-dialog entrypoints into one navigable
namespace. Physical modules live in their original paths.
"""
from __future__ import annotations

try:
    from mcp_server import (  # noqa: F401
        build_default_registry,
        ToolCall,
        ToolRegistry,
        ToolResult,
    )
except Exception:  # noqa: BLE001
    build_default_registry = None  # type: ignore[assignment]
    ToolCall = None                # type: ignore[assignment]
    ToolRegistry = None            # type: ignore[assignment]
    ToolResult = None              # type: ignore[assignment]

try:
    from agents.owner_dialog import (  # noqa: F401
        OwnerDialogDispatcher,
        build_default_handlers,
        notify_owner,
    )
except Exception:  # noqa: BLE001
    OwnerDialogDispatcher = None       # type: ignore[assignment]
    build_default_handlers = None      # type: ignore[assignment]
    notify_owner = None                # type: ignore[assignment]

try:
    from core.adapters.telegram_bot import (  # noqa: F401
        TelegramBotAdapter,
    )
except Exception:  # noqa: BLE001
    TelegramBotAdapter = None          # type: ignore[assignment]

# Quality-audit item #10: AgentManager is a first-class
# owner-facing surface (lifecycle + registry for every
# specialised agent) but it wasn't reachable through the
# interface facade. Re-export + expose the canonical
# singleton so CLI / dashboard / MCP callers don't have to
# reach into ``agents.manager``.
try:
    from agents.manager import (  # noqa: F401
        AgentManager,
        get_agent_manager,
    )
except Exception:  # noqa: BLE001
    AgentManager = None                # type: ignore[assignment]
    get_agent_manager = None           # type: ignore[assignment]


__all__ = [
    "AgentManager",
    "OwnerDialogDispatcher",
    "TelegramBotAdapter",
    "ToolCall",
    "ToolRegistry",
    "ToolResult",
    "build_default_handlers",
    "build_default_registry",
    "get_agent_manager",
    "notify_owner",
]
