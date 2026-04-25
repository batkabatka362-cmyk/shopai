"""CRM adapter bootstrap (stub: HubSpot/Salesforce/Klaviyo not wired)."""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry

logger = get_logger("adapters.crm.bootstrap")


def register_all(registry: AdapterRegistry | None = None) -> dict[str, bool]:
    logger.debug("crm bootstrap: no adapters implemented")
    return {}
