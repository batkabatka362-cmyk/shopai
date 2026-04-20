"""adapters/ — top-level facade for external adapters.

Physical modules live under ``core/adapters/`` (legacy) and
the newer sibling packages. This facade gives callers
``import adapters.shopify`` or ``import adapters.fal`` style
paths without physically moving files (per
docs/FOLDER_REORG_PLAN.md Phase 2).

External adapters indexed here:
  * shopify        — modern GraphQL + legacy REST
  * telegram_bot   — owner dialog bus
  * fulfillment    — CJ Dropshipping (+ future AutoDS, etc.)
  * trends         — Google Trends, TikTok trending
  * triplewhale    — Moby Agents (Wave C-1)
  * fal            — fal.ai video router (Wave D-1)
  * obsidian       — vault read-back + memory_bridge
"""
from __future__ import annotations

try:
    from core.adapters.shopify.modern_client import (  # noqa: F401
        ShopifyModernClient,
    )
except Exception:  # noqa: BLE001
    ShopifyModernClient = None  # type: ignore[assignment]

try:
    from core.adapters.telegram_bot import (  # noqa: F401
        TelegramBotAdapter,
    )
except Exception:  # noqa: BLE001
    TelegramBotAdapter = None    # type: ignore[assignment]

try:
    from core.adapters.fulfillment import (  # noqa: F401
        CJFulfillAdapter,
    )
except Exception:  # noqa: BLE001
    CJFulfillAdapter = None      # type: ignore[assignment]

try:
    from core.adapters.trends import (  # noqa: F401
        GoogleTrendsAdapter,
    )
except Exception:  # noqa: BLE001
    GoogleTrendsAdapter = None   # type: ignore[assignment]

try:
    from core.adapters.triplewhale import (  # noqa: F401
        MobyAdapter,
    )
except Exception:  # noqa: BLE001
    MobyAdapter = None           # type: ignore[assignment]

try:
    from core.adapters.fal import (  # noqa: F401
        FalVideoRouter,
    )
except Exception:  # noqa: BLE001
    FalVideoRouter = None        # type: ignore[assignment]


__all__ = [
    "CJFulfillAdapter",
    "FalVideoRouter",
    "GoogleTrendsAdapter",
    "MobyAdapter",
    "ShopifyModernClient",
    "TelegramBotAdapter",
]
