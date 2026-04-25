"""Browser adapter bootstrap (stub: Playwright/Puppeteer not wired)."""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry

logger = get_logger("adapters.browser.bootstrap")


def register_all(registry: AdapterRegistry | None = None) -> dict[str, bool]:
    logger.debug("browser bootstrap: no adapters implemented")
    return {}
