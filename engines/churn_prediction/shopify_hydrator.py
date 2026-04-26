"""Churn Prediction Engine — Shopify customer hydrator.

The churn prediction engine expects callers to supply a ``customers``
list. Without auto-hydration, callers had to pre-fetch the customer
roster via platforms/shopify.py or stage it in a CSV before invoking
the engine. With the SmartRouter wired and 129 Shopify adapters live,
the engine can now read its inputs autonomously when the caller
leaves them empty.

Mirrors the shape of ``engines.bundle.shopify_hydrator``:
  * Pass-through when supplied is non-empty.
  * Auto-fetch via ``Capability.SHOPIFY_FETCH_CUSTOMERS`` when empty.
  * Returns whatever was supplied (empty if nothing) on every
    failure mode — engine's own validation still emits its standard
    "requires non-empty list" error.

Optional ``query`` filter passes through to the API. Useful for
scoping churn analysis to a cohort: ``"orders_count:>0 AND
last_order_date:<2026-01-01"`` etc.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("churn_prediction.shopify_hydrator")


_DEFAULT_HYDRATE_LIMIT = 250
_MAX_HYDRATE_LIMIT = 250
_MIN_HYDRATE_LIMIT = 1


def hydrate_customers(
    supplied: list[dict[str, Any]] | None,
    *,
    limit: int | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Return customer list, fetching from Shopify when supplied is empty.

    Args:
        supplied: Whatever the caller passed under ``data.customers``.
            Non-empty → returned unchanged (no network call).
        limit: Optional hydrate-call page size cap (1-250). Defaults
            to 250.
        query: Optional Shopify customer-search filter
            (e.g. ``"orders_count:>0 AND last_order_date:<2026-01-01"``).
            Skipped when None / blank.

    Returns:
        The supplied list, OR the auto-fetched normalised customer
        list, OR an empty list if nothing's available (caller-side
        validation still emits the engine's standard "requires
        customers" error downstream).
    """
    if supplied:
        return supplied

    router = _get_router()
    capability = _get_capability("SHOPIFY_FETCH_CUSTOMERS")
    if router is None or capability is None:
        return []

    params: dict[str, Any] = {"limit": _clamp_limit(limit)}
    if isinstance(query, str) and query.strip():
        params["query"] = query.strip()

    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug("customer hydrate raised: %s", exc)
        return []

    if not getattr(result, "ok", False):
        logger.debug(
            "customer hydrate failed: %s",
            getattr(result, "error", "unknown"),
        )
        return []

    data = getattr(result, "data", {}) or {}
    customers = data.get("customers") or []
    return [c for c in customers if isinstance(c, dict)]


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
