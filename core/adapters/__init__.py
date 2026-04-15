"""ShopAI adapter layer.

ShopAI's "Lego principle" surface. Every external dependency
(Shopify Admin API, Klaviyo, Gemini, Groq, Ollama, Firecrawl, …)
implements ``BaseAdapter`` and registers with ``AdapterRegistry``.
The brain asks the ``SmartRouter`` for a *capability* and the
router picks the right adapter at call time — vendor swaps
become a config change instead of a rewrite.

Quick start
-----------

::

    from core.adapters import (
        get_registry, get_router, Capability, RouteContext,
    )

    # 1. Adapters self-register at import time (see core.adapters.llm)
    from core.adapters.llm import groq, gemini  # noqa: F401

    # 2. Brain asks for a capability
    result = get_router().execute(
        Capability.CHAT_COMPLETE,
        {"prompt": "Why are sales down this week?"},
        context=RouteContext(budget_usd=0.01),
    )

    if result.ok:
        print(result.data["text"])
"""
from .base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from .config import AdapterConfig, ENV_ALIASES, get_config, reset_config
from .errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterQuotaExhausted,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
    CaptchaDetected,
)
from .metrics import AdapterMetrics, MetricsCollector, get_metrics, reset_metrics
from .registry import AdapterRegistry, get_registry, reset_registry
from .router import (
    NoAdapterAvailable,
    RouteContext,
    SmartRouter,
    get_router,
    reset_router,
)

__all__ = [
    # Base
    "AdapterCategory",
    "AdapterResult",
    "BaseAdapter",
    "Capability",
    # Errors
    "AdapterAuthError",
    "AdapterError",
    "AdapterNotConfigured",
    "AdapterQuotaExhausted",
    "AdapterRateLimited",
    "AdapterTimeout",
    "AdapterUnavailable",
    "AdapterValidationError",
    "CaptchaDetected",
    "NoAdapterAvailable",
    # Config
    "AdapterConfig",
    "ENV_ALIASES",
    "get_config",
    "reset_config",
    # Metrics
    "AdapterMetrics",
    "MetricsCollector",
    "get_metrics",
    "reset_metrics",
    # Registry
    "AdapterRegistry",
    "get_registry",
    "reset_registry",
    # Router
    "RouteContext",
    "SmartRouter",
    "get_router",
    "reset_router",
]
