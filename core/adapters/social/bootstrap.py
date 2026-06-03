"""Social adapter bootstrap.

Registers every social-media adapter with AdapterRegistry.
Same idempotency contract as the other adapter-family bootstraps
(LLM, email, ads, shopify, search, shipping, image).
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .pinterest import PinterestAdapter

logger = get_logger("adapters.social.bootstrap")


# Module-level class list -- discovered by the Pattern I audit
# walker so SOCIAL_* capabilities surface as claimed even when
# the live bootstrap hasn't been invoked yet.
_SOCIAL_ADAPTER_CLASSES = [
    PinterestAdapter,
]


def register_all(
    registry: AdapterRegistry | None = None,
) -> int:
    reg = registry if registry is not None else get_registry()
    adapters_to_register = [
        cls() for cls in _SOCIAL_ADAPTER_CLASSES
    ]
    count = 0
    for adapter in adapters_to_register:
        if reg.get(adapter.name) is None:
            reg.register(adapter)
            count += 1
    logger.debug(
        "social.bootstrap: registered %d adapter(s)", count,
    )
    return count
