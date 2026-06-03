"""CRO Variants — Pattern Q envelope wrapper.

Input:
  data.product:      dict with title/description/category/price
                     (preferred when pre-fetched)
  data.product_id:   gid://shopify/Product/X (hydrates via
                     SHOPIFY_GET_PRODUCT when 'product' is absent)
  data.strategies:   list of which to generate
                     (default: title + description + price)
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .variant_generator import (
    description_variants,
    price_variants,
    title_variants,
)

logger = logging.getLogger(__name__)


_DEFAULT_STRATEGIES = ("title", "description", "price")


class CroVariantsEngine:
    ENGINE_NAME = "cro_variants"

    def run(
        self, input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = time.monotonic()
        payload = self._safe_copy(input_payload)
        if payload is None:
            return self._fail("Input copy failed", 0.0)
        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        # Resolve product: prefer supplied, fall back to hydration.
        product = data.get("product")
        product_id = data.get("product_id")

        if not isinstance(product, dict):
            if not product_id:
                return self._fail(
                    "product or product_id required",
                    time.monotonic() - start,
                )
            product = self._hydrate_product(str(product_id))
            if product is None:
                return self._fail(
                    f"could not hydrate product "
                    f"'{product_id}'",
                    time.monotonic() - start,
                )

        title = str(product.get("title") or "").strip()
        description = str(
            product.get("description")
            or product.get("body_html")
            or "",
        )
        category = str(
            product.get("category")
            or product.get("product_type")
            or "",
        )
        try:
            current_price = float(
                product.get("price")
                or product.get("current_price")
                or 0.0,
            )
        except (TypeError, ValueError):
            current_price = 0.0

        if not title:
            return self._fail(
                "product missing title",
                time.monotonic() - start,
            )

        # Strategy resolution.
        strategies_raw = data.get("strategies")
        if not strategies_raw:
            strategies = list(_DEFAULT_STRATEGIES)
        else:
            if isinstance(strategies_raw, str):
                strategies_raw = [
                    s.strip()
                    for s in strategies_raw.split(",")
                ]
            strategies = [
                s.lower() for s in strategies_raw if s
            ]

        out_variants: dict[str, list[dict[str, Any]]] = {}
        if "title" in strategies:
            out_variants["title"] = [
                asdict(v) for v in title_variants(
                    title=title, category=category,
                )
            ]
        if "description" in strategies:
            out_variants["description"] = [
                asdict(v) for v in description_variants(
                    description=description,
                    title=title,
                    category=category,
                )
            ]
        if "price" in strategies:
            out_variants["price"] = [
                asdict(v) for v in price_variants(
                    current_price=current_price,
                )
            ]

        return self._success(
            {
                "product_id": product_id or "",
                "product_title": title,
                "product_category": category,
                "product_price": current_price,
                "strategies": strategies,
                "variants": out_variants,
                "next_action": (
                    "Pick one variant per strategy + run via "
                    "Shopify theme A/B or shopai engine run "
                    "ab_testing for experiment design."
                ),
            },
            start,
        )

    # ── Internal ──────────────────────────────────────────

    @staticmethod
    def _safe_copy(payload: Any) -> Any:
        if payload is None:
            return {}
        try:
            return copy.deepcopy(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("input copy raised: %s", exc)
            return None

    @staticmethod
    def _hydrate_product(product_id: str) -> dict[str, Any] | None:
        """Pull product via SHOPIFY_GET_PRODUCT. Returns None when
        the router / adapter is unavailable."""
        try:
            from core.adapters.router import get_router
            from core.adapters.base import Capability
            router = get_router()
            result = router.execute(
                Capability.SHOPIFY_GET_PRODUCT,
                {"id": product_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "cro_variants hydrate raised: %s", exc,
            )
            return None
        if not getattr(result, "ok", False):
            return None
        data = getattr(result, "data", None) or {}
        if isinstance(data, dict):
            return data
        return None

    def _success(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "data": data,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(
                    time.monotonic() - start, 3,
                ),
            },
            "error": None,
        }

    def _fail(
        self, reason: str, elapsed: float,
    ) -> dict[str, Any]:
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
