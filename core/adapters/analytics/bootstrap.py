"""Analytics adapter bootstrap.

Stub: no concrete analytics adapters (Google Analytics, Mixpanel,
Amplitude, etc.) are wired in yet. Returns an empty status map so
``AutonomousController.initialize`` can aggregate it with the
configured categories without tripping an ``ImportError``.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry

logger = get_logger("adapters.analytics.bootstrap")


def register_all(registry: AdapterRegistry | None = None) -> dict[str, bool]:
    logger.debug("analytics bootstrap: no adapters implemented")
    return {}
