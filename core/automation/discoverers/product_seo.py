"""Discoverer for the product_seo autonomy domain (W828).

Walks live products, surfaces SEO metadata gaps, and emits
update_seo payloads. The applier writes meta_title /
meta_description; the discoverer's job is to find products
where those fields are missing or empty and suggest a
heuristic replacement.

Rules (one event per gap; up to 2 events per product if both
title + description are missing):

  meta_title missing or empty   -> propose product title (or
                                    first 80 chars of the body
                                    if title also missing)
  meta_description missing or
    < 50 visible chars          -> propose first 160 chars of
                                    visible description text

Proposed values are clamped to the applier's max-length env
(default 320) less a safety margin. The applier's
``exceeds_max_length`` gate is the second line of defense.

Env: ``SHOPAI_PRODUCT_SEO_DISCOVER_LIMIT`` (default 100).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from core.automation.payload_discoverer import (
    DiscoveryResult,
    register_discoverer,
)

logger = logging.getLogger(__name__)

_DOMAIN = "product_seo"
_DEFAULT_LIMIT = 100
_MIN_DESC_CHARS = 50
_PROPOSE_DESC_CHARS = 160
_PROPOSE_TITLE_CHARS = 80


def _limit() -> int:
    raw = os.environ.get(
        "SHOPAI_PRODUCT_SEO_DISCOVER_LIMIT",
        str(_DEFAULT_LIMIT),
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT


def _strip_html(text: str) -> str:
    """Pragmatic HTML strip -- preserves spaces around tags."""
    return (
        text.replace("<p>", "")
        .replace("</p>", " ")
        .replace("<br>", " ")
        .replace("<br/>", " ")
        .replace("<br />", " ")
        .strip()
    )


def _propose_for(product: dict[str, Any]) -> list[dict]:
    """Return 0-2 payload rows for one product."""
    rows: list[dict] = []
    if not isinstance(product, dict):
        return rows

    pid = str(product.get("id") or product.get("gid") or "")
    pid = pid.strip()
    if not pid:
        return rows
    sid = str(product.get("store_id") or "").strip()

    seo = product.get("seo") or {}
    if not isinstance(seo, dict):
        seo = {}
    cur_title = str(seo.get("title") or "").strip()
    cur_desc = str(seo.get("description") or "").strip()

    title = str(product.get("title") or "").strip()
    body = _strip_html(str(
        product.get("body_html") or product.get("description")
        or "",
    ))

    if not cur_title:
        proposal = title or body[:_PROPOSE_TITLE_CHARS]
        proposal = proposal.strip()
        if proposal:
            rows.append({
                "product_id": pid,
                "store_id": sid,
                "action": "update_seo",
                "field": "meta_title",
                "new_value": proposal[
                    :_PROPOSE_TITLE_CHARS
                ],
                "signal_source": "product_seo_discoverer",
            })

    if len(cur_desc) < _MIN_DESC_CHARS:
        proposal = body[:_PROPOSE_DESC_CHARS].strip()
        if not proposal and title:
            proposal = title
        if proposal:
            rows.append({
                "product_id": pid,
                "store_id": sid,
                "action": "update_seo",
                "field": "meta_description",
                "new_value": proposal[
                    :_PROPOSE_DESC_CHARS
                ],
                "signal_source": "product_seo_discoverer",
            })
    return rows


def _fetch_products() -> list[dict[str, Any]]:
    try:
        from core.adapters.router import get_router  # noqa
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_seo discoverer: router import raised: %s",
            exc,
        )
        return []
    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_seo discoverer: router unavail: %s", exc,
        )
        return []
    cap = getattr(Capability, "SHOPIFY_LIST_PRODUCTS", None)
    if cap is None:
        return []
    try:
        res = router.execute(cap, {"limit": _limit()})
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_seo discoverer: execute raised: %s", exc,
        )
        return []
    if not getattr(res, "ok", False):
        return []
    data = getattr(res, "data", None) or {}
    products = (
        data.get("products") if isinstance(data, dict) else None
    )
    if not isinstance(products, list):
        return []
    return products


def discover_product_seo(*, store_id: str | None = None) -> DiscoveryResult:
    now = time.time()
    try:
        products = _fetch_products()
    except Exception as exc:  # noqa: BLE001
        return DiscoveryResult(
            domain=_DOMAIN,
            payload=[],
            source="shopify_products",
            discovered_at=now,
            store_id=store_id,
            error=f"fetch raised: {exc!s:.200}",
        )
    payload: list[dict] = []
    for p in products:
        payload.extend(_propose_for(p))
    return DiscoveryResult(
        domain=_DOMAIN,
        payload=payload,
        source="shopify_products",
        discovered_at=now,
            store_id=store_id,
    )


register_discoverer(_DOMAIN, discover_product_seo)
