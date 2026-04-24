"""AmazonSPAdapter — Amazon Selling Partner API (2026+).

Z6 multi-platform mission. Adds Amazon as a reachable
marketplace alongside Shopify + TikTok Shop.

Auth: LWA (Login with Amazon) refresh_token → access_token
exchange; AWS sig v4 is no longer required for most
endpoints as of Nov 2024 — Bearer access_token is sufficient
for Orders + Catalog Items APIs, which is the minimum
surface we need. Restricted data tokens (RDT) for PII are
NOT fetched by this adapter — ``list_orders`` uses the
minimal-field signature that doesn't need one. Callers
needing customer addresses later should ship a dedicated
RDT flow.

Regions:
  na → https://sellingpartnerapi-na.amazon.com  (US / CA / MX)
  eu → https://sellingpartnerapi-eu.amazon.com  (UK / DE / FR / IT / ES)
  fe → https://sellingpartnerapi-fe.amazon.com  (JP / AU / SG)

Capabilities:
  * AMAZON_LIST_ORDERS     — GET /orders/v0/orders
  * AMAZON_GET_ORDER       — GET /orders/v0/orders/{id}
  * AMAZON_SEARCH_CATALOG  — GET /catalog/2022-04-01/items

Hard guardrail (§4b.G): NO product listing / publish /
fulfillment methods. Amazon catalog / listing writes are a
separate wave with their own test gate.
"""
from __future__ import annotations

import datetime
import logging
import os
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False


logger = logging.getLogger("shopai.adapters.marketplace.amazon")


_REGION_HOSTS = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}
_DEFAULT_REGION = "na"
_DEFAULT_MARKETPLACE = "ATVPDKIKX0DER"  # amazon.com (US)

_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
_TOKEN_REFRESH_LEAD_S = 60.0
_DEFAULT_TIMEOUT = 30.0


@dataclass
class _CachedToken:
    value: str = ""
    expires_at_monotonic: float = 0.0


class AmazonSPAdapter(BaseAdapter):
    """Amazon SP-API adapter — read-only surface (orders +
    catalog search)."""

    name = "amazon_sp"
    category = AdapterCategory.MARKETPLACE
    capabilities = {
        Capability.AMAZON_LIST_ORDERS,
        Capability.AMAZON_GET_ORDER,
        Capability.AMAZON_SEARCH_CATALOG,
    }
    priority = 60
    cost_per_call = 0.0
    timeout = _DEFAULT_TIMEOUT

    def __init__(self) -> None:
        super().__init__()
        self._token_lock = threading.Lock()
        self._token = _CachedToken()

    # ── Configuration ─────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        cfg = get_config()
        for key in (
            "amazon_sp_client_id",
            "amazon_sp_client_secret",
            "amazon_sp_refresh_token",
        ):
            if not cfg.get(key):
                return False
        return True

    def _region(self) -> str:
        region = (
            str(
                get_config().get("amazon_sp_region")
                or _DEFAULT_REGION,
            )
            .strip()
            .lower()
        )
        if region not in _REGION_HOSTS:
            region = _DEFAULT_REGION
        return region

    @property
    def base_url(self) -> str:
        return _REGION_HOSTS[self._region()]

    def _marketplace_ids(self) -> list[str]:
        raw = str(
            get_config().get("amazon_sp_marketplace_ids") or "",
        ).strip()
        if not raw:
            return [_DEFAULT_MARKETPLACE]
        return [
            p.strip() for p in raw.split(",") if p.strip()
        ]

    # ── LWA token ─────────────────────────────────────

    def _access_token(self) -> str:
        now = time.monotonic()
        if (
            self._token.value
            and now < self._token.expires_at_monotonic
            - _TOKEN_REFRESH_LEAD_S
        ):
            return self._token.value
        with self._token_lock:
            now = time.monotonic()
            if (
                self._token.value
                and now < self._token.expires_at_monotonic
                - _TOKEN_REFRESH_LEAD_S
            ):
                return self._token.value
            tok, ttl = self._fetch_token()
            self._token = _CachedToken(
                value=tok,
                expires_at_monotonic=(
                    time.monotonic() + max(ttl, 0.0)
                ),
            )
            return self._token.value

    def _fetch_token(self) -> tuple[str, float]:
        cfg = get_config()
        client_id = cfg.get("amazon_sp_client_id")
        client_secret = cfg.get("amazon_sp_client_secret")
        refresh = cfg.get("amazon_sp_refresh_token")
        if not (client_id and client_secret and refresh):
            raise AdapterNotConfigured(
                self.name,
                "missing LWA credentials — set "
                "AMAZON_SP_CLIENT_ID + "
                "AMAZON_SP_CLIENT_SECRET + "
                "AMAZON_SP_REFRESH_TOKEN",
            )
        if not _REQUESTS_AVAILABLE:
            raise AdapterError(
                self.name, "'requests' not installed",
            )
        try:
            resp = _requests.post(
                _TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"LWA refresh failed: "
                f"{type(exc).__name__}: {exc}",
            ) from exc
        status = getattr(resp, "status_code", 0)
        if status in (401, 403):
            raise AdapterAuthError(
                self.name,
                f"LWA rejected credentials ({status})",
            )
        if status >= 400:
            snippet = (
                getattr(resp, "text", "") or ""
            )[:200]
            raise AdapterError(
                self.name,
                f"LWA returned {status}: {snippet}",
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise AdapterError(
                self.name, f"LWA non-JSON body: {exc}",
            ) from exc
        tok = (
            payload.get("access_token", "")
            if isinstance(payload, dict) else ""
        )
        if not tok:
            raise AdapterError(
                self.name,
                "LWA missing access_token in response",
            )
        ttl = float(payload.get("expires_in", 0) or 0)
        return str(tok), ttl

    # ── Dispatch ─────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability == Capability.AMAZON_LIST_ORDERS:
            return self._do_list_orders(params)
        if capability == Capability.AMAZON_GET_ORDER:
            return self._do_get_order(params)
        if capability == Capability.AMAZON_SEARCH_CATALOG:
            return self._do_search_catalog(params)
        raise AdapterValidationError(
            self.name,
            f"unsupported capability: {capability.value}",
        )

    # ── Capability implementations ───────────────────

    def _do_list_orders(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        """GET /orders/v0/orders. Filters via query params:

          * ``created_after``  — ISO-8601 or Y-m-d. Defaults
            to now - 7 days.
          * ``created_before`` — ISO-8601 (optional).
          * ``order_statuses`` — list. Default
            ["Unshipped"].
          * ``max_results_per_page`` — 1-100, default 100.
        """
        marketplaces = self._marketplace_ids()
        created_after = str(
            params.get("created_after") or "",
        ).strip()
        if not created_after:
            created_after = _iso_utc_days_ago(7)
        statuses = params.get("order_statuses") or [
            "Unshipped",
        ]
        if not isinstance(statuses, (list, tuple)):
            raise AdapterValidationError(
                self.name,
                "'order_statuses' must be a list",
            )
        try:
            per_page = max(
                1,
                min(
                    int(params.get("max_results_per_page", 100)),
                    100,
                ),
            )
        except (TypeError, ValueError):
            per_page = 100

        query: dict[str, Any] = {
            "MarketplaceIds": ",".join(marketplaces),
            "CreatedAfter": created_after,
            "OrderStatuses": ",".join(
                str(s) for s in statuses if s
            ),
            "MaxResultsPerPage": per_page,
        }
        created_before = str(
            params.get("created_before") or "",
        ).strip()
        if created_before:
            query["CreatedBefore"] = created_before

        raw = self._sp_request(
            "GET", "/orders/v0/orders", query=query,
        )
        payload = (raw.get("payload") or {})
        orders_raw = payload.get("Orders") or []
        orders: list[dict[str, Any]] = []
        if isinstance(orders_raw, list):
            for row in orders_raw:
                if not isinstance(row, dict):
                    continue
                orders.append(_normalise_order(row))
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.AMAZON_LIST_ORDERS.value,
            data={
                "orders": orders,
                "total": len(orders),
                "next_token": str(
                    payload.get("NextToken") or "",
                ),
                "marketplace_ids": marketplaces,
            },
            raw=raw,
        )

    def _do_get_order(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        order_id = str(params.get("order_id") or "").strip()
        if not order_id:
            raise AdapterValidationError(
                self.name, "'order_id' is required",
            )
        raw = self._sp_request(
            "GET", f"/orders/v0/orders/{order_id}",
        )
        payload = raw.get("payload") or {}
        if not isinstance(payload, dict):
            raise AdapterError(
                self.name,
                "unexpected order payload shape",
            )
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.AMAZON_GET_ORDER.value,
            data={"order": _normalise_order(payload)},
            raw=raw,
        )

    def _do_search_catalog(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        keywords = str(params.get("keywords") or "").strip()
        asin = str(params.get("asin") or "").strip()
        if not keywords and not asin:
            raise AdapterValidationError(
                self.name,
                "one of 'keywords' or 'asin' required",
            )
        marketplaces = self._marketplace_ids()
        try:
            page_size = max(
                1,
                min(int(params.get("page_size", 10)), 20),
            )
        except (TypeError, ValueError):
            page_size = 10

        query: dict[str, Any] = {
            "marketplaceIds": ",".join(marketplaces),
            "pageSize": page_size,
            "includedData":
                "identifiers,attributes,summaries,images",
        }
        if keywords:
            query["keywords"] = keywords
        if asin:
            query["identifiers"] = asin
            query["identifiersType"] = "ASIN"
        raw = self._sp_request(
            "GET",
            "/catalog/2022-04-01/items",
            query=query,
        )
        items_raw = raw.get("items") or []
        items: list[dict[str, Any]] = []
        if isinstance(items_raw, list):
            for row in items_raw:
                if not isinstance(row, dict):
                    continue
                items.append(_normalise_catalog_item(row))
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.AMAZON_SEARCH_CATALOG.value,
            data={
                "items": items,
                "total": len(items),
                "marketplace_ids": marketplaces,
            },
            raw=raw,
        )

    # ── HTTP ─────────────────────────────────────────

    def _sp_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            clean = {
                k: v for k, v in query.items()
                if v is not None and v != ""
            }
            if clean:
                url = (
                    f"{url}?"
                    + urllib.parse.urlencode(clean)
                )
        headers = {
            "x-amz-access-token": self._access_token(),
            "Accept": "application/json",
            "User-Agent": "ShopAI-AmazonSP/1.0",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"

        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' not installed",
            )
        try:
            if method == "GET":
                resp = _requests.get(
                    url, headers=headers,
                    timeout=self.timeout,
                )
            else:
                resp = _requests.request(
                    method, url,
                    headers=headers, json=body,
                    timeout=self.timeout,
                )
        except _requests.Timeout as exc:  # type: ignore[union-attr]
            raise AdapterTimeout(
                self.name,
                f"timeout after {self.timeout}s: {exc}",
            ) from exc
        except _requests.ConnectionError as exc:  # type: ignore[union-attr]
            raise AdapterUnavailable(
                self.name, f"connection error: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"HTTP {method} failed: "
                f"{type(exc).__name__}: {exc}",
            ) from exc

        status = getattr(resp, "status_code", 0)
        if status >= 400:
            snippet = (
                getattr(resp, "text", "") or ""
            )[:200]
            if status in (401, 403):
                raise AdapterAuthError(
                    self.name,
                    f"Amazon rejected credentials "
                    f"({status}): {snippet}",
                )
            if status == 429:
                raise AdapterRateLimited(
                    self.name,
                    f"rate limit (429): {snippet}",
                )
            if 500 <= status < 600:
                raise AdapterUnavailable(
                    self.name,
                    f"Amazon 5xx ({status}): {snippet}",
                )
            raise AdapterError(
                self.name,
                f"Amazon returned {status}: {snippet}",
            )

        try:
            text = getattr(resp, "text", "") or ""
            return resp.json() if text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name,
                f"invalid JSON response: {exc}",
            ) from exc


# ── Helpers ───────────────────────────────────────────


def _iso_utc_days_ago(days: int) -> str:
    dt = datetime.datetime.now(
        datetime.timezone.utc,
    ) - datetime.timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalise_order(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise Amazon's CapitalCase fields to snake_case."""
    total_amount_block = row.get("OrderTotal") or {}
    try:
        total = float(total_amount_block.get("Amount") or 0)
    except (TypeError, ValueError):
        total = 0.0
    try:
        item_count = int(
            row.get("NumberOfItemsShipped", 0) or 0,
        ) + int(
            row.get("NumberOfItemsUnshipped", 0) or 0,
        )
    except (TypeError, ValueError):
        item_count = 0
    return {
        "order_id": str(
            row.get("AmazonOrderId") or "",
        ),
        "status": str(row.get("OrderStatus") or ""),
        "purchase_date": str(
            row.get("PurchaseDate") or "",
        ),
        "last_update_date": str(
            row.get("LastUpdateDate") or "",
        ),
        "total_amount": round(total, 2),
        "currency": str(
            total_amount_block.get("CurrencyCode") or "",
        ),
        "marketplace_id": str(
            row.get("MarketplaceId") or "",
        ),
        "fulfillment_channel": str(
            row.get("FulfillmentChannel") or "",
        ),
        "sales_channel": str(
            row.get("SalesChannel") or "",
        ),
        "buyer_info_anonymised": bool(
            (row.get("BuyerInfo") or {}).get(
                "BuyerEmail", "",
            ).endswith("@marketplace.amazon.com"),
        ),
        "item_count": item_count,
        "shipment_service_level": str(
            row.get("ShipmentServiceLevelCategory")
            or "",
        ),
        "is_prime": bool(row.get("IsPrime")),
        "is_business_order": bool(
            row.get("IsBusinessOrder"),
        ),
    }


def _normalise_catalog_item(
    row: dict[str, Any],
) -> dict[str, Any]:
    summaries = row.get("summaries") or []
    summary: dict[str, Any] = (
        summaries[0] if summaries and isinstance(
            summaries[0], dict,
        ) else {}
    )
    images = row.get("images") or []
    image_url = ""
    if isinstance(images, list) and images:
        first_set = images[0] or {}
        img_list = (
            first_set.get("images") or []
        )
        if isinstance(img_list, list) and img_list:
            image_url = str(
                img_list[0].get("link") or "",
            )
    return {
        "asin": str(row.get("asin") or ""),
        "title": str(summary.get("itemName") or ""),
        "brand": str(summary.get("brand") or ""),
        "manufacturer": str(
            summary.get("manufacturer") or "",
        ),
        "item_classification": str(
            summary.get("itemClassification") or "",
        ),
        "image_url": image_url,
    }
