"""CJ Dropshipping fulfillment adapter — order + tracking (LX.2).

Sprint 3 S3-8 (P2). Pair to ``agents/research/sources/cj_dropshipping``
(winner discovery) — this module handles the post-sale leg: when a
Shopify order for a CJ-sourced product lands, we place the CJ-side
dropship order, record the tracking id, and surface updates back
to the customer.

Auth: same email + api_key exchange as the discovery source. Token
is cached 6h. Missing credentials → ``is_available()`` is False and
every call is a no-op with last_error populated.

Narrow surface:

  * ``place_order(order_spec)``   → ``FulfillmentOrder`` with
    fulfillment_id + status, or None on failure.
  * ``get_tracking(order_id)``    → ``TrackingUpdate`` or None.
  * ``list_orders(limit=50)``     → recent fulfillments.
  * ``stats()``                    → token state + last_error.

Idempotency: CJ's createOrder endpoint accepts a
``shopifyOrderNumber`` field — passing the same Shopify order
number twice is a no-op on their end. We also dedupe locally via
an in-memory set so retries don't hit their rate limit.

Pure stdlib + requests. Thread-safe (Lock). Deterministic under a
fixed http client.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.adapters.fulfillment.cj_fulfill")


_DEFAULT_TIMEOUT = 20.0
_AUTH_PATH = "/api2.0/v1/authentication/getAccessToken"
_CREATE_ORDER_PATH = "/api2.0/v1/shopping/order/createOrder"
_ORDER_DETAIL_PATH = "/api2.0/v1/shopping/order/getOrderDetail"
_TRACK_PATH = "/api2.0/v1/logistic/trackInfo"
_LIST_ORDERS_PATH = "/api2.0/v1/shopping/order/list"
_DEFAULT_BASE = "https://developers.cjdropshipping.com"
_TOKEN_LIFETIME_S = 6 * 3600.0


@dataclass
class FulfillmentOrder:
    fulfillment_id: str          # CJ's orderId
    shopify_order_number: str
    status: str = "pending"
    created_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "fulfillment_id": self.fulfillment_id,
            "shopify_order_number": (
                self.shopify_order_number
            ),
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass
class TrackingUpdate:
    tracking_number: str
    carrier: str
    status: str
    events: tuple[dict[str, Any], ...] = ()
    last_update_ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tracking_number": self.tracking_number,
            "carrier": self.carrier,
            "status": self.status,
            "events": list(self.events),
            "last_update_ts": self.last_update_ts,
        }


class CJFulfillAdapter:
    """CJ Open Platform order placement + tracking."""

    name = "cj_fulfill"

    def __init__(
        self,
        *,
        email: str = "",
        api_key: str = "",
        base_url: str = _DEFAULT_BASE,
        timeout: float = _DEFAULT_TIMEOUT,
        http: Any = None,
        now_fn: Any = None,
    ) -> None:
        self._email = (
            email
            or os.environ.get("CJ_EMAIL", "")
        )
        self._api_key = (
            api_key
            or os.environ.get("CJ_API_KEY", "")
        )
        self._base = str(base_url).rstrip("/")
        self._timeout = float(timeout)
        self._http = http
        self._now_fn = now_fn or time.time
        self._lock = threading.Lock()
        self._token = ""
        self._token_ts = 0.0
        self._last_error = ""
        self._placed_local: set[str] = set()
        self._recent: list[FulfillmentOrder] = []

    def is_available(self) -> bool:
        return bool(self._email) and bool(self._api_key)

    # ── Auth ─────────────────────────────────────────────

    def _client(self) -> Any:
        if self._http is not None:
            return self._http
        import requests
        return requests

    def _get_token(self) -> str:
        now = float(self._now_fn())
        with self._lock:
            if (
                self._token
                and now - self._token_ts < _TOKEN_LIFETIME_S
            ):
                return self._token
        resp = self._client().post(
            f"{self._base}{_AUTH_PATH}",
            json={
                "email": self._email,
                "password": self._api_key,
            },
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"auth HTTP {resp.status_code}: "
                f"{(resp.text or '')[:120]}"
            )
        body = resp.json() or {}
        token = str(
            body.get("data", {}).get("accessToken", ""),
        )
        if not token:
            raise RuntimeError(
                "auth returned empty accessToken",
            )
        with self._lock:
            self._token = token
            self._token_ts = now
        return token

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "CJ-Access-Token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Order placement ──────────────────────────────────

    def place_order(
        self,
        *,
        shopify_order_number: str,
        shipping_address: dict[str, Any],
        line_items: list[dict[str, Any]],
        note: str = "",
    ) -> FulfillmentOrder | None:
        """Place a dropship order on CJ's side.

        ``line_items`` entries require at minimum ``productId`` (CJ
        SKU) and ``quantity``. Returns a ``FulfillmentOrder`` with
        CJ's orderId on success, None on failure.
        """
        if not self.is_available():
            with self._lock:
                self._last_error = (
                    "not configured — set CJ_EMAIL + "
                    "CJ_API_KEY"
                )
            return None
        if not shopify_order_number:
            with self._lock:
                self._last_error = (
                    "shopify_order_number required"
                )
            return None
        if not line_items:
            with self._lock:
                self._last_error = "line_items required"
            return None
        # Local dedupe — CJ also dedupes on their side via
        # shopifyOrderNumber but we spare the RTT on duplicates.
        with self._lock:
            if shopify_order_number in self._placed_local:
                for existing in self._recent:
                    if (
                        existing.shopify_order_number
                        == shopify_order_number
                    ):
                        return existing
        try:
            token = self._get_token()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"auth: {exc}"
            logger.debug(
                "cj auth failed: %s", exc,
            )
            return None
        try:
            resp = self._client().post(
                f"{self._base}{_CREATE_ORDER_PATH}",
                json={
                    "shopifyOrderNumber": (
                        shopify_order_number
                    ),
                    "shippingAddress": dict(
                        shipping_address,
                    ),
                    "products": list(line_items),
                    "remark": note,
                },
                headers=self._headers(token),
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = (
                    f"createOrder exception: {exc}"
                )
            return None
        if resp.status_code >= 400:
            with self._lock:
                self._last_error = (
                    f"createOrder HTTP "
                    f"{resp.status_code}: "
                    f"{(resp.text or '')[:120]}"
                )
            return None
        try:
            body = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = (
                    f"bad createOrder JSON: {exc}"
                )
            return None
        if body.get("code") not in (200, 0) and not body.get(
            "result",
        ):
            with self._lock:
                self._last_error = (
                    "cj rejected: "
                    + str(body.get("message", "unknown"))
                )
            return None
        data = body.get("data") or {}
        cj_order_id = str(
            data.get("orderId") or data.get("id", ""),
        )
        if not cj_order_id:
            with self._lock:
                self._last_error = (
                    "cj returned empty orderId"
                )
            return None
        order = FulfillmentOrder(
            fulfillment_id=cj_order_id,
            shopify_order_number=shopify_order_number,
            status=str(data.get("orderStatus") or "pending"),
            created_at=float(self._now_fn()),
        )
        with self._lock:
            self._placed_local.add(shopify_order_number)
            self._recent.append(order)
            # Cap recent list so it never grows unbounded
            if len(self._recent) > 200:
                self._recent = self._recent[-200:]
            self._last_error = ""
        return order

    # ── Tracking ─────────────────────────────────────────

    def get_tracking(
        self, *, tracking_number: str,
    ) -> TrackingUpdate | None:
        if not self.is_available():
            with self._lock:
                self._last_error = "not configured"
            return None
        if not tracking_number:
            with self._lock:
                self._last_error = (
                    "tracking_number required"
                )
            return None
        try:
            token = self._get_token()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"auth: {exc}"
            return None
        try:
            resp = self._client().get(
                f"{self._base}{_TRACK_PATH}",
                params={"trackNumber": tracking_number},
                headers=self._headers(token),
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = (
                    f"trackInfo exception: {exc}"
                )
            return None
        if resp.status_code >= 400:
            with self._lock:
                self._last_error = (
                    f"trackInfo HTTP {resp.status_code}"
                )
            return None
        try:
            body = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"bad JSON: {exc}"
            return None
        data = body.get("data") or {}
        events = data.get("trackingEvents") or data.get(
            "events", []
        ) or []
        return TrackingUpdate(
            tracking_number=tracking_number,
            carrier=str(data.get("carrier") or ""),
            status=str(
                data.get("status")
                or data.get("trackingStatus")
                or "unknown",
            ),
            events=tuple(
                e for e in events if isinstance(e, dict)
            ),
            last_update_ts=float(self._now_fn()),
        )

    # ── Diagnostics ──────────────────────────────────────

    def list_orders(
        self, *, limit: int = 50,
    ) -> list[FulfillmentOrder]:
        with self._lock:
            return list(self._recent[-int(limit):])

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "adapter": self.name,
                "configured": bool(
                    self._email and self._api_key,
                ),
                "has_token": bool(self._token),
                "token_age_s": (
                    float(self._now_fn()) - self._token_ts
                    if self._token else 0.0
                ),
                "orders_placed": len(self._placed_local),
                "last_error": self._last_error,
            }
