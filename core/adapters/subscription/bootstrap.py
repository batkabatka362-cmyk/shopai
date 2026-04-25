"""Subscription adapter bootstrap (stub: Recharge/Bold/Loop not wired)."""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry

logger = get_logger("adapters.subscription.bootstrap")


def register_all(registry: AdapterRegistry | None = None) -> dict[str, bool]:
    logger.debug("subscription bootstrap: no adapters implemented")
    return {}
