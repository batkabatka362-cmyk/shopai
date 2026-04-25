"""Automation adapter bootstrap (stub: Zapier/Make/n8n not wired)."""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry

logger = get_logger("adapters.automation.bootstrap")


def register_all(registry: AdapterRegistry | None = None) -> dict[str, bool]:
    logger.debug("automation bootstrap: no adapters implemented")
    return {}
