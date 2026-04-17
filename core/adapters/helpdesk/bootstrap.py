"""Helpdesk adapter bootstrap (stub: Zendesk/Intercom/Gorgias not wired)."""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry

logger = get_logger("adapters.helpdesk.bootstrap")


def register_all(registry: AdapterRegistry | None = None) -> dict[str, bool]:
    logger.debug("helpdesk bootstrap: no adapters implemented")
    return {}
