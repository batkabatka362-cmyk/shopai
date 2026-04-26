"""Bundle Engine — Shopify catalog hydrator.

The bundle engine expects callers to supply a ``products`` list (and
optionally ``orders``) up front. Pre-migration, callers had to read
that data out-of-band — typically by hitting platforms/shopify.py
directly or staging the data in a CSV. With the SmartRouter wired,
the engine can now read its inputs autonomously when the caller
leaves them empty.

Behavior:

  * Caller supplies non-empty ``products`` → pass-through, no
    network call. Empty / missing → call
    ``Capability.SHOPIFY_LIST_PRODUCTS`` via the router and return
    the normalised product list.
  * Caller supplies non-empty ``orders`` → pass-through. Empty /
    missing → call ``Capability.SHOPIFY_FETCH_ORDERS`` and use the
    result for affinity analysis. Orders are OPTIONAL — affinity
    analyser tolerates an empty list — so failure here is silent.
  * Router unavailable / adapter failure → return whatever was
    supplied (empty if nothing). Pipeline downstream still emits
    its standard "Product list is required" error in that case,
    same as today.

The hydrator is a no-op for callers that already pass full data —
the auto-fetch only kicks in when the caller hasn't stitched the
read themselves. Page-size cap defaults to 250 products / 250
orders per call (configurable via ``hydrate_limit`` on the input
data block) — bundle analysis on huge catalogues is a separate
optimization that's out of scope here.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("bundle.shopify_hydrator")


_DEFAULT_HYDRATE_LIMIT = 250
_MAX_HYDRATE_LIMIT = 250
_MIN_HYDRATE_LIMIT = 1


def hydrate_products(
    supplied: list[dict[str, Any]] | None,
    *,
    limit: int | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Return product list, fetching from Shopify when supplied is empty.

    Args:
        supplied: Whatever the caller passed under ``data.products``.
            If non-empty, returned unchanged (no network call).
        limit: Optional hydrate-call page size cap (1-250). Honors
            the supplied value or falls back to 250.
        query: Optional Shopify product-search filter
            (e.g. ``status:active AND tag:bestseller``). Skipped
            when None.

    Returns:
        The supplied list, OR the auto-fetched normalised product
        list, OR an empty list if nothing's available (caller-side
        validation will then emit the "Product list is required"
        error downstream).
    """
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
    return [
        p for p in products if isinstance(p, dict)
    ]


def hydrate_orders(
    supplied: list[dict[str, Any]] | None,
    *,
    limit: int | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Return order list, fetching from Shopify when supplied is empty.

    Mirrors hydrate_products. Returns an empty list on any failure
    (orders are OPTIONAL for affinity analysis — the engine still
    builds bundles from products alone, just without co-purchase
    signal).
    """
    if supplied:
        return supplied

    router = _get_router()
    capability = _get_capability("SHOPIFY_FETCH_ORDERS")
    if router is None or capability is None:
        return []

    params: dict[str, Any] = {"limit": _clamp_limit(limit)}
    if isinstance(query, str) and query.strip():
        params["query"] = query.strip()

    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug("order hydrate raised: %s", exc)
        return []

    if not getattr(result, "ok", False):
        logger.debug(
            "order hydrate failed: %s",
            getattr(result, "error", "unknown"),
        )
        return []

    data = getattr(result, "data", {}) or {}
    orders = data.get("orders") or []
    return [o for o in orders if isinstance(o, dict)]


# ── Helpers ────────────────────────────────────────────────────


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
