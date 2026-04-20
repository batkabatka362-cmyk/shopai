"""orchestrator/ — facade re-exports for the orchestration layer.

Per docs/FOLDER_REORG_PLAN.md Phase 2. Physical modules live
under ``core/`` and ``scripts/`` — this package gives callers
a clean ``import orchestrator.XYZ`` surface without moving any
files. All existing imports keep working.
"""
from __future__ import annotations

# Autopilot daemon loop (24/7 cycle runner)
try:
    from scripts.autopilot_loop import (  # noqa: F401
        AutopilotLoop,
    )
except Exception:  # noqa: BLE001
    AutopilotLoop = None  # type: ignore[assignment]

# Owner dialog daemon (Telegram poll + digest push)
try:
    from scripts.owner_loop import OwnerLoop  # noqa: F401
except Exception:  # noqa: BLE001
    OwnerLoop = None  # type: ignore[assignment]

# Campaign activator (PAUSED → ACTIVE safety chain)
try:
    from execution.launch.campaign_activator import (  # noqa: F401
        CampaignActivator,
    )
except Exception:  # noqa: BLE001
    CampaignActivator = None  # type: ignore[assignment]

# Publisher bundle (winner → Shopify + Meta)
try:
    from execution.launch.publisher_bundle import (  # noqa: F401
        PublisherBundle,
    )
except Exception:  # noqa: BLE001
    PublisherBundle = None  # type: ignore[assignment]


__all__ = [
    "AutopilotLoop",
    "CampaignActivator",
    "OwnerLoop",
    "PublisherBundle",
]
