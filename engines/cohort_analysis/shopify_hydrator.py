"""Cohort Analysis Engine — Shopify customer + order hydrator.

Cohort analysis needs BOTH customers and orders to do its job —
customers carry signup dates (cohort assignment), orders carry the
purchase events (retention math). Pre-migration, callers had to
pre-fetch both before invoking the engine. With the SmartRouter wired
and 129 Shopify adapters live, the engine now fetches its own data
when the caller leaves either list empty.

Mirrors the bundle (Phase 28.2) + churn_prediction (Phase 28.3)
hydrators in shape — pass-through for non-empty supplied,
auto-fetch via the appropriate Capability when empty, returns
whatever was supplied (empty if nothing) on every failure mode.

Two capabilities used:
  * ``Capability.SHOPIFY_FETCH_CUSTOMERS`` for the customers list.
  * ``Capability.SHOPIFY_FETCH_ORDERS`` for the orders list.

Either can be supplied or hydrated independently — cohort_analysis
will run as long as ONE of them is non-empty (the engine's own
"customers OR orders required" check still fires when both
hydrations also produce nothing).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("cohort_analysis.shopify_hydrator")


_DEFAULT_HYDRATE_LIMIT = 250
_MAX_HYDRATE_LIMIT = 250
_MIN_HYDRATE_LIMIT = 1


def hydrate_customers(
    supplied: list[dict[str, Any]] | None,
    *,
    limit: int | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Pass-through if supplied; else fetch via SHOPIFY_FETCH_CUSTOMERS."""
    return _hydrate(
        supplied=supplied,
        capability_name="SHOPIFY_FETCH_CUSTOMERS",
        list_field="customers",
        limit=limit,
        query=query,
    )


def hydrate_orders(
    supplied: list[dict[str, Any]] | None,
    *,
    limit: int | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Pass-through if supplied; else fetch via SHOPIFY_FETCH_ORDERS."""
    return _hydrate(
        supplied=supplied,
        capability_name="SHOPIFY_FETCH_ORDERS",
        list_field="orders",
        limit=limit,
        query=query,
    )


# ── Private ────────────────────────────────────────────────────


def _hydrate(
    *,
    supplied: list[dict[str, Any]] | None,
    capability_name: str,
    list_field: str,
    limit: int | None,
    query: str | None,
) -> list[dict[str, Any]]:
    if supplied:
        return supplied

    router = _get_router()
    capability = _get_capability(capability_name)
    if router is None or capability is None:
        return []

    params: dict[str, Any] = {"limit": _clamp_limit(limit)}
    if isinstance(query, str) and query.strip():
        params["query"] = query.strip()

    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "%s hydrate raised: %s", list_field, exc,
        )
        return []

    if not getattr(result, "ok", False):
        logger.debug(
            "%s hydrate failed: %s",
            list_field, getattr(result, "error", "unknown"),
        )
        return []

    data = getattr(result, "data", {}) or {}
    items = data.get(list_field) or []
    return [i for i in items if isinstance(i, dict)]


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
