"""Catalog Engine — Shopify product hydrator.

Mirrors the bundle / churn_prediction / cohort_analysis hydrators —
auto-fetches the catalog's product list via
``Capability.SHOPIFY_LIST_PRODUCTS`` when the caller leaves it empty.
Pass-through otherwise.

Returns whatever was supplied (empty if nothing) on every failure
mode — engine's own validation downstream still emits its standard
errors.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("catalog.shopify_hydrator")


_DEFAULT_HYDRATE_LIMIT = 250
_MAX_HYDRATE_LIMIT = 250
_MIN_HYDRATE_LIMIT = 1


def hydrate_products(
    supplied: list[dict[str, Any]] | None,
    *,
    limit: int | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Pass-through if supplied; else fetch via SHOPIFY_LIST_PRODUCTS."""
    if supplied:
        return supplied

    router = _get_router()
    capability = _get_capability("SHOPIFY_LIST_PRODUCTS")
    if router is None or capability is None:
        return []

    params: dict[str, Any] = {"limit": _clamp_limit(limit)}
    if isinstance(query, str) and query.strip():
        params["query"] = query.strip()

    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug("product hydrate raised: %s", exc)
        return []

    if not getattr(result, "ok", False):
        logger.debug(
            "product hydrate failed: %s",
            getattr(result, "error", "unknown"),
        )
        return []

    data = getattr(result, "data", {}) or {}
    products = data.get("products") or []
    return [p for p in products if isinstance(p, dict)]


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router
    except Exception as exc:  # noqa: BLE001
        logger.debug("router import failed: %s", exc)
        return None
    try:
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("router init failed: %s", exc)
        return None


def _get_capability(name: str) -> Any | None:
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return getattr(Capability, name, None)


def _clamp_limit(raw: Any) -> int:
    if raw is None:
        return _DEFAULT_HYDRATE_LIMIT
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_HYDRATE_LIMIT
    return max(_MIN_HYDRATE_LIMIT, min(n, _MAX_HYDRATE_LIMIT))
