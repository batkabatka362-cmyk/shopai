"""Discoverer for the catalog_quality autonomy domain (W824).

Walks the live product catalog from Shopify, applies a small
heuristic per product, maps to one curated catalog-quality
tag. Returns a payload ready for the catalog_quality applier.

Mapping (heuristic, conservative):

  Image count == 0                 -> shopai-quality-needs-images
  Description length < 80 chars    -> shopai-quality-thin-description
  Has 0 variants (or 1 default)    -> shopai-quality-no-variants
  Status == "draft" or hidden      -> shopai-quality-flagged-review
  Otherwise (passes all checks)    -> shopai-quality-validated

Per-product the FIRST matching rule wins (in the order above)
so a single product can't generate multiple tag events.

If the Shopify router is unavailable / no products, returns
an empty payload with no error.

Default scan size: 100 products. Override via
``SHOPAI_CATALOG_QUALITY_DISCOVER_LIMIT``.
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

_DOMAIN = "catalog_quality"
_DEFAULT_LIMIT = 100
_THIN_DESC_CHARS = 80


def _limit(store_id: str | None = None) -> int:
    """W881: per-store override via
    SHOPAI_CATALOG_QUALITY_DISCOVER_LIMIT_<STORE>."""
    from core.automation.discoverer_env import resolve_int
    return resolve_int(
        _DOMAIN, "LIMIT",
        default=_DEFAULT_LIMIT,
        store_id=store_id,
        min_value=1,
    )


def _classify_product(prod: dict[str, Any]) -> str | None:
    """Map a Shopify product dict to one quality tag. None
    means "skip this product" (no signal)."""
    if not isinstance(prod, dict):
        return None
    images = prod.get("images") or []
    if isinstance(images, list) and len(images) == 0:
        return "shopai-quality-needs-images"

    desc = str(prod.get("body_html") or prod.get(
        "description",
    ) or "")
    # Strip simple HTML so we measure visible text length.
    visible = (
        desc.replace("<p>", "")
        .replace("</p>", "")
        .replace("<br>", " ")
        .strip()
    )
    if len(visible) < _THIN_DESC_CHARS:
        return "shopai-quality-thin-description"

    variants = prod.get("variants") or []
    if isinstance(variants, list):
        non_default = [
            v for v in variants
            if isinstance(v, dict) and v.get("title") not in (
                None, "", "Default Title",
            )
        ]
        if not non_default:
            return "shopai-quality-no-variants"

    status = str(prod.get("status") or "").lower()
    if status in ("draft", "archived"):
        return "shopai-quality-flagged-review"

    return "shopai-quality-validated"


def _fetch_products(
    store_id: str | None = None,
) -> list[dict[str, Any]]:
    """Pull a page of products via SmartRouter. [] on
    unavailable."""
    try:
        from core.adapters.router import get_router  # noqa
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "catalog_quality discoverer: router import "
            "raised: %s", exc,
        )
        return []
    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "catalog_quality discoverer: router unavail: %s",
            exc,
        )
        return []
    cap = getattr(Capability, "SHOPIFY_LIST_PRODUCTS", None)
    if cap is None:
        return []
    try:
        res = router.execute(cap, {"limit": _limit(store_id)})
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "catalog_quality discoverer: execute raised: %s",
            exc,
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


def discover_catalog_quality(*, store_id: str | None = None) -> DiscoveryResult:
    now = time.time()
    try:
        products = _fetch_products(store_id=store_id)
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
        if not isinstance(p, dict):
            continue
        tag = _classify_product(p)
        if tag is None:
            continue
        pid = str(p.get("id") or p.get("gid") or "").strip()
        if not pid:
            continue
        sid = str(p.get("store_id") or "").strip()
        payload.append({
            "product_id": pid,
            "store_id": sid,
            "action": "tag_quality",
            "tag": tag,
            "signal_source": "catalog_quality_discoverer",
        })
    return DiscoveryResult(
        domain=_DOMAIN,
        payload=payload,
        source="shopify_products",
        discovered_at=now,
            store_id=store_id,
    )


register_discoverer(_DOMAIN, discover_catalog_quality)
