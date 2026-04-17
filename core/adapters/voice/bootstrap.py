"""Voice adapter bootstrap (stub: Twilio Voice/ElevenLabs not wired)."""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry

logger = get_logger("adapters.voice.bootstrap")


def register_all(registry: AdapterRegistry | None = None) -> dict[str, bool]:
    logger.debug("voice bootstrap: no adapters implemented")
    return {}
