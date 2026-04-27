"""Shared Shopify hydrator — extracted from per-engine duplication.

Phases 28.2-28.5 each shipped a hydrator that follows the same
shape: pass-through if the caller pre-fetched, else call a Shopify
``Capability`` via the SmartRouter and return the normalised list.
The 4 per-engine modules (bundle, churn_prediction, cohort_analysis,
catalog) duplicated ~110 lines of boilerplate each.

This module is the single source of truth for that pattern.
Per-engine modules now stay thin: they just call ``hydrate()``
with the right capability name + response field.

Public API::

    from engines._shopify_hydrator import hydrate

    def hydrate_products(supplied, *, limit=None, query=None):
        return hydrate(
            supplied=supplied,
            capability_name="SHOPIFY_LIST_PRODUCTS",
            list_field="products",
            limit=limit,
            query=query,
        )

The behavior is identical to the old per-engine hydrators:

  * Non-empty ``supplied`` → returned unchanged (no router call).
  * Empty/None → router lookup + capability lookup; if either is
    unavailable, returns an empty list.
  * Adapter raises / returns ``ok=False`` → empty list.
  * Any non-dict items in the response are filtered out.
  * Limit defaults to 250, clamped to [1, 250]. Override via the
    ``limit`` kwarg. Override the clamp ceiling per-call by
    passing ``max_limit``.
  * Optional ``query`` kwarg passes through to the API. Blank /
    whitespace-only queries are dropped (Shopify rejects them).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("engines.shopify_hydrator")


_DEFAULT_HYDRATE_LIMIT = 250
_DEFAULT_MAX_LIMIT = 250
_MIN_LIMIT = 1


def hydrate(
    *,
    supplied: list[dict[str, Any]] | None,
    capability_name: str,
    list_field: str,
    limit: int | None = None,
    query: str | None = None,
    max_limit: int = _DEFAULT_MAX_LIMIT,
    extra_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Pass-through if supplied; else fetch via the named Capability.

    Args:
        supplied: The list the caller passed (e.g. ``data.products``).
            If non-empty, returned unchanged with no router lookup.
        capability_name: Attribute name on ``Capability`` enum
            (e.g. ``"SHOPIFY_LIST_PRODUCTS"``,
            ``"SHOPIFY_FETCH_CUSTOMERS"``).
        list_field: Key in the adapter response that holds the
            normalised list (e.g. ``"products"``, ``"customers"``,
            ``"orders"``).
        limit: Optional page-size cap. Defaults to 250.
        query: Optional Shopify search filter
            (e.g. ``"status:active AND tag:bestseller"``).
            Blank/whitespace-only strings are dropped.
        max_limit: Override the clamp ceiling. Defaults to 250.
        extra_params: Optional extra keys to merge into the
            adapter call params (e.g. ``{"sort_key": "TITLE"}``).

    Returns:
        The supplied list unchanged, OR the auto-fetched list,
        OR ``[]`` on any failure mode (caller-side validation
        downstream still emits its standard error).
    """
    if supplied:
        return supplied

    router = _get_router()
    capability = _get_capability(capability_name)
    if router is None or capability is None:
        return []

    params: dict[str, Any] = {
        "limit": _clamp_limit(limit, max_limit=max_limit),
    }
    if isinstance(query, str) and query.strip():
        params["query"] = query.strip()
    if isinstance(extra_params, dict):
        for k, v in extra_params.items():
            if v is not None:
                params[k] = v

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


def hydrate_one(
    *,
    supplied: dict[str, Any] | None,
    capability_name: str,
    list_field: str,
    query: str | None = None,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pass-through if supplied (non-empty dict); else fetch one item.

    Singular-input variant of :func:`hydrate`. Some engines take a
    ``data.product`` (dict) rather than ``data.products`` (list);
    this helper calls the same Capability with ``limit=1`` and
    returns the first item, or an empty dict.

    Args:
        supplied: The dict the caller passed (e.g. ``data.product``).
            If non-empty (truthy), returned unchanged.
        capability_name: Same as :func:`hydrate`.
        list_field: Same as :func:`hydrate` — the key holding the
            normalised list in the adapter response.
        query: Optional Shopify search filter.
        extra_params: Optional extra keys to merge into the call.

    Returns:
        The supplied dict unchanged, OR the first auto-fetched item,
        OR ``{}`` on any failure mode.
    """
    if isinstance(supplied, dict) and supplied:
        return supplied

    items = hydrate(
        supplied=[],
        capability_name=capability_name,
        list_field=list_field,
        limit=1,
        query=query,
        extra_params=extra_params,
    )
    return items[0] if items else {}


# ── Helpers (also exported for direct use by per-engine wrappers) ──


def _get_router() -> Any | None:
    """Lazy-import the router. Returns ``None`` if unavailable."""
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
    """Look up a Capability enum entry by name. ``None`` if missing."""
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return getattr(Capability, name, None)


def _clamp_limit(
    raw: Any,
    *,
    max_limit: int = _DEFAULT_MAX_LIMIT,
) -> int:
    if raw is None:
        return min(_DEFAULT_HYDRATE_LIMIT, max_limit)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return min(_DEFAULT_HYDRATE_LIMIT, max_limit)
    return max(_MIN_LIMIT, min(n, max_limit))
