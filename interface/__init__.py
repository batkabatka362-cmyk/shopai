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


__all__ = [
    "OwnerDialogDispatcher",
    "TelegramBotAdapter",
    "ToolCall",
    "ToolRegistry",
    "ToolResult",
    "build_default_handlers",
    "build_default_registry",
    "notify_owner",
]
