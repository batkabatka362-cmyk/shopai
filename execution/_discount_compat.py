"""W963-157: REST `price_rules.json` → GraphQL compat shim.

The live stress test against the beauty store surfaced a 403:

    Shopify GET price_rules.json failed: HTTP 403:
    "[API] This action requires merchant approval for
    read_price_rules scope."

`read_price_rules` is a deprecated scope; ShopAI's adapter
layer removed it long ago. But three legacy callers in
`execution/` still hit `price_rules.json` REST + 5
`price_rules.json` POST endpoints. This module is the
single GraphQL replacement they all funnel through.

Public API:
  - ``list_existing_discount_titles(client)`` -> set[str]
  - ``create_code_discount(code, value_pct, **kwargs)`` -> dict

Both go through the SmartRouter so per-store credentials,
scope manifest declarations, and Pattern J test guards all
work correctly.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)


def list_existing_discount_titles(
    client: Any | None = None,
) -> set[str]:
    """Return the title set of existing code discounts.

    ``client`` is accepted for backward-compat with REST
    callers but is unused -- the router handles per-store
    credential routing via the active_store thread-local.

    Returns an empty set on any failure (router unavailable,
    scope missing, etc.) so the caller's idempotent create
    just re-attempts -- safe because Shopify's discount
    create paths dedup by title anyway.
    """
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "discount_compat router import failed: %s", exc,
        )
        return set()
    # W963-177: paginate through ALL discounts, not just the
    # first 250. Established stores with marketing teams running
    # quarterly promos easily accumulate 250+ codes; capping at
    # one page meant dedup would miss any code beyond #250 +
    # store_configurator would try to re-create them, hitting
    # Shopify's unique-code rejection. Cap at 10 pages (2,500
    # codes) as a runaway safety net.
    titles: set[str] = set()
    cursor: str | None = None
    try:
        router = get_router()
        for _ in range(10):
            params: dict[str, Any] = {"limit": 250}
            if cursor:
                params["cursor"] = cursor
            result = router.execute(
                Capability.SHOPIFY_LIST_DISCOUNTS, params,
            )
            if not getattr(result, "ok", False):
                break
            data = getattr(result, "data", None) or {}
            for d in data.get("discounts") or []:
                if not isinstance(d, dict):
                    continue
                title = d.get("title") or d.get("code") or ""
                if isinstance(title, str) and title:
                    titles.add(title)
            if not data.get("has_next_page"):
                break
            cursor = data.get("end_cursor") or ""
            if not cursor:
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "discount_compat list_discounts raised: %s",
            exc,
        )
        # Return what we collected so far (partial is better
        # than empty -- still useful for dedup)
        return titles
    return titles


def create_code_discount(
    code: str,
    value_pct: float,
    *,
    description: str = "",
    once_per_customer: bool = False,
    usage_limit: int | None = None,
    target_type: str = "line_item",
    min_subtotal: float | None = None,
    min_qty: int | None = None,
    starts_at: str | None = None,
) -> dict[str, Any]:
    """Create a percentage-based code discount via GraphQL.

    Mirrors the friendly shape used by every legacy REST
    caller in ``execution/``. ``value_pct`` is the percentage
    in -100..0 form (e.g. ``-15.0`` = 15% off). Returns a
    dict with ``ok``, ``discount_id``, ``code``, plus any
    error string on failure -- never raises.
    """
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "discount_compat router import failed: %s", exc,
        )
        return {"ok": False, "error": str(exc), "code": code}

    pct = abs(float(value_pct)) / 100.0
    starts = starts_at or time.strftime(
        "%Y-%m-%dT00:00:00Z",
    )

    params: dict[str, Any] = {
        "code": code,
        "title": code,
        "value_percentage": pct,
        "starts_at": starts,
        "applies_once_per_customer": once_per_customer,
    }
    if description:
        params["description"] = description
    if usage_limit is not None:
        params["usage_limit"] = int(usage_limit)
    if min_subtotal is not None:
        params["minimum_subtotal"] = float(min_subtotal)
    if min_qty is not None:
        params["minimum_quantity"] = int(min_qty)
    if target_type:
        params["target_type"] = target_type

    try:
        router = get_router()
        result = router.execute(
            Capability.SHOPIFY_CREATE_DISCOUNT, params,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "discount_compat create raised: %s", exc,
        )
        return {"ok": False, "error": str(exc), "code": code}

    if not getattr(result, "ok", False):
        return {
            "ok": False,
            "error": str(
                getattr(result, "error", "unknown"),
            ),
            "code": code,
        }
    data = getattr(result, "data", None) or {}
    return {
        "ok": True,
        "discount_id": data.get("discount_id", ""),
        "code": code,
    }
