"""Web search adapter bootstrap.

Single entry point that instantiates every search adapter and
registers it with ``AdapterRegistry``. Mirrors the LLM and
Shopify bootstraps so the controller can call all three at
startup with the same idempotency guarantees.

Usage::

    from core.adapters.search.bootstrap import register_all
    register_all()

Adapters whose API key is unset still register; the smart
router skips them via ``is_configured()``. The DDGS adapter
has no API key and is therefore always available — it acts
as the default fallback whenever the cloud search adapters
are not configured.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .brave import BraveSearchAdapter
from .ddgs import DDGSAdapter
from .exa import ExaAdapter
from .perplexity import PerplexityAdapter
from .serper import SerperAdapter
from .similarweb import SimilarWebAdapter
from .tavily import TavilyAdapter

logger = get_logger("adapters.search.bootstrap")


_SEARCH_ADAPTER_CLASSES = (
    BraveSearchAdapter,
    PerplexityAdapter,
    SerperAdapter,
    TavilyAdapter,
    ExaAdapter,
    SimilarWebAdapter,
    DDGSAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every search adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map.
    """
    reg = registry or get_registry()
    status: dict[str, bool] = {}

    for cls in _SEARCH_ADAPTER_CLASSES:
        try:
            adapter = cls()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to instantiate %s: %s", cls.__name__, exc,
            )
            continue

        try:
            reg.register(adapter, replace=True)
            status[adapter.name] = adapter.is_configured()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to register %s: %s", adapter.name, exc,
            )

    configured = sum(1 for v in status.values() if v)
    logger.info(
        "Search adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
