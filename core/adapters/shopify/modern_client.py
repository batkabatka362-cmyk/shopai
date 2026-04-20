"""Modern Shopify GraphQL Admin client (2024-10+).

User request C. ``_base.py`` + legacy ``ShopifyGraphQL`` work
against older API versions. This module adds a thin, 2024-10-
era client with:

  * Explicit version pinning — default ``2024-10``, overrideable
    per call; falls back to ``2024-07`` if the server rejects
    a newer version.
  * ``X-Shopify-Access-Token`` header (current auth method) +
    JSON Content-Type.
  * Cost-aware throttling — reads ``extensions.cost`` out of
    every response and maintains a token bucket model to
    back off before Shopify returns a 429.
  * Idempotent mutations via a top-level ``clientRequestId``
    input field (supported for create/update product / variant
    mutations in 2024-10+).
  * Retry with exponential backoff on 429 + network errors; a
    single shared retry budget per request.
  * Pure stdlib + requests. No dependency on the older
    ``ShopifyGraphQL`` class.

Scope (intentionally narrow):

  * ``ShopifyModernClient(shop_url, access_token, api_version)``
  * ``execute(query, variables, client_request_id)`` → dict
  * ``query_product(gid, fields=DEFAULT_FIELDS)`` helper
  * ``product_set(input, client_request_id)`` — 2024-10 unified
    upsert mutation
  * ``stats()`` exposes throttle state for debug

Future helpers (variants, inventory, orders) can ride on top of
``execute`` without touching this file.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.adapters.shopify.modern_client")


_DEFAULT_API_VERSION = "2024-10"
_FALLBACK_API_VERSION = "2024-07"
_DEFAULT_TIMEOUT = 20.0
_DEFAULT_RETRIES = 4
_GRAPHQL_PATH = "/admin/api/{version}/graphql.json"

# Token-bucket defaults per Shopify docs: 100 points available,
# restore 50/s for standard stores. Plus / Enterprise allow
# 200/1000, we keep the conservative default.
_DEFAULT_MAX_POINTS = 100
_DEFAULT_RESTORE_PER_S = 50.0


@dataclass
class ThrottleState:
    current_available: float
    max_available: float
    restore_rate: float
    last_update_ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "current_available": round(
                self.current_available, 2,
            ),
            "max_available": round(
                self.max_available, 2,
            ),
            "restore_rate": round(self.restore_rate, 2),
            "last_update_ts": self.last_update_ts,
        }


class ShopifyThrottleError(Exception):
    pass


class ShopifyModernClient:
    """2024-10 GraphQL Admin client with throttle awareness."""

    def __init__(
        self,
        *,
        shop_url: str,
        access_token: str,
        api_version: str = _DEFAULT_API_VERSION,
        fallback_version: str = _FALLBACK_API_VERSION,
        timeout: float = _DEFAULT_TIMEOUT,
        retries: int = _DEFAULT_RETRIES,
        http: Any = None,
        now_fn: Any = None,
        sleep_fn: Any = None,
    ) -> None:
        if not shop_url or not access_token:
            raise ValueError(
                "shop_url + access_token required",
            )
        if retries < 0:
            raise ValueError("retries must be ≥ 0")
        self._shop = shop_url.rstrip("/")
        self._token = access_token
        self._version = api_version
        self._fallback = fallback_version
        self._timeout = float(timeout)
        self._retries = int(retries)
        self._http = http
        self._now_fn = now_fn or time.time
        self._sleep_fn = sleep_fn or time.sleep
        self._lock = threading.Lock()
        self._throttle = ThrottleState(
            current_available=_DEFAULT_MAX_POINTS,
            max_available=_DEFAULT_MAX_POINTS,
            restore_rate=_DEFAULT_RESTORE_PER_S,
            last_update_ts=float(self._now_fn()),
        )
        self._calls = 0
        self._throttled_calls = 0

    # ── Endpoint + headers ──────────────────────────────

    def _endpoint(self, version: str) -> str:
        path = _GRAPHQL_PATH.format(version=version)
        shop = self._shop
        if not shop.startswith("http"):
            shop = f"https://{shop}"
        return f"{shop}{path}"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Shopify-Access-Token": self._token,
        }

    def _client(self) -> Any:
        if self._http is not None:
            return self._http
        import requests
        return requests

    # ── Throttle model ───────────────────────────────────

    def _update_throttle(
        self,
        extensions: dict[str, Any] | None,
    ) -> None:
        if not extensions:
            return
        cost = extensions.get("cost") or {}
        status = cost.get("throttleStatus") or {}
        try:
            current = float(
                status.get("currentlyAvailable", 0),
            )
            maximum = float(
                status.get("maximumAvailable", 0),
            )
            restore = float(
                status.get("restoreRate", 0),
            )
        except (TypeError, ValueError):
            return
        with self._lock:
            self._throttle = ThrottleState(
                current_available=current,
                max_available=(
                    maximum
                    if maximum > 0
                    else self._throttle.max_available
                ),
                restore_rate=(
                    restore
                    if restore > 0
                    else self._throttle.restore_rate
                ),
                last_update_ts=float(self._now_fn()),
            )

    def _wait_if_needed(self, required_cost: float) -> None:
        with self._lock:
            available = self._throttle.current_available
            restore = self._throttle.restore_rate
        if available >= required_cost:
            return
        if restore <= 0:
            return
        deficit = required_cost - available
        wait_s = deficit / restore
        if wait_s > 0:
            logger.debug(
                "throttle wait %.2fs (need %.1f, have %.1f)",
                wait_s, required_cost, available,
            )
            self._sleep_fn(min(wait_s, 5.0))

    # ── Execute ──────────────────────────────────────────

    def execute(
        self,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
        client_request_id: str | None = None,
        expected_cost: float = 1.0,
        api_version: str | None = None,
    ) -> dict[str, Any]:
        """Run a GraphQL query/mutation against the modern API.

        ``client_request_id`` is injected into ``variables``
        (mutations supporting idempotency should accept it at
        the input root — e.g. ``productSet(input: $input,
        synchronous: true)`` with an application-provided id).
        """
        if not query:
            raise ValueError("query required")
        body: dict[str, Any] = {"query": query}
        vars_final = dict(variables or {})
        if client_request_id is None:
            client_request_id = uuid.uuid4().hex
        vars_final.setdefault(
            "clientRequestId", client_request_id,
        )
        body["variables"] = vars_final
        use_version = api_version or self._version
        self._wait_if_needed(expected_cost)
        return self._send_with_retry(
            body=body, version=use_version,
        )

    def _send_with_retry(
        self,
        *,
        body: dict[str, Any],
        version: str,
    ) -> dict[str, Any]:
        attempt = 0
        backoff = 1.0
        last_exc: Exception | None = None
        while attempt <= self._retries:
            attempt += 1
            try:
                resp = self._client().post(
                    self._endpoint(version),
                    headers=self._headers(),
                    data=json.dumps(body),
                    timeout=self._timeout,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.debug(
                    "network exception attempt %d: %s",
                    attempt, exc,
                )
                self._sleep_fn(backoff)
                backoff = min(backoff * 2, 16.0)
                continue
            status = int(
                getattr(resp, "status_code", 0),
            )
            if status == 429:
                with self._lock:
                    self._throttled_calls += 1
                self._sleep_fn(backoff)
                backoff = min(backoff * 2, 16.0)
                continue
            if (
                status in (400, 406)
                and version != self._fallback
            ):
                # Unknown API version → try fallback once
                logger.debug(
                    "version %s rejected, trying %s",
                    version, self._fallback,
                )
                return self._send_with_retry(
                    body=body, version=self._fallback,
                )
            if status >= 400:
                raise ShopifyThrottleError(
                    f"HTTP {status}: "
                    f"{(getattr(resp, 'text', '') or '')[:120]}"
                )
            try:
                data = resp.json() or {}
            except Exception as exc:  # noqa: BLE001
                raise ShopifyThrottleError(
                    f"bad JSON: {exc}",
                ) from exc
            self._update_throttle(
                data.get("extensions") or {},
            )
            with self._lock:
                self._calls += 1
            return data
        raise ShopifyThrottleError(
            f"exceeded retries ({self._retries}); "
            f"last error: {last_exc}"
        )

    # ── Convenience helpers ─────────────────────────────

    def query_product(
        self,
        *,
        gid: str,
        fields: tuple[str, ...] = (
            "id", "title", "handle", "status",
            "seoTitle", "seoDescription",
        ),
    ) -> dict[str, Any]:
        if not gid:
            raise ValueError("gid required")
        selector = "\n    ".join(fields)
        query = (
            "query ($id: ID!, $clientRequestId: String) {\n"
            "  product(id: $id) {\n"
            f"    {selector}\n"
            "  }\n"
            "}"
        )
        return self.execute(
            query,
            variables={"id": gid},
            expected_cost=1.0,
        )

    def product_set(
        self,
        *,
        product_input: dict[str, Any],
        client_request_id: str | None = None,
    ) -> dict[str, Any]:
        """Shopify 2024-10 unified upsert. Idempotent when a
        stable clientRequestId is supplied by the caller."""
        if not product_input:
            raise ValueError("product_input required")
        query = (
            "mutation productSet("
            "$input: ProductSetInput!, "
            "$clientRequestId: String"
            ") {\n"
            "  productSet(input: $input) {\n"
            "    product { id handle }\n"
            "    userErrors { field message }\n"
            "  }\n"
            "}"
        )
        return self.execute(
            query,
            variables={"input": product_input},
            client_request_id=client_request_id,
            expected_cost=10.0,
        )

    # ── Introspection ───────────────────────────────────

    def throttle(self) -> ThrottleState:
        with self._lock:
            return ThrottleState(
                current_available=(
                    self._throttle.current_available
                ),
                max_available=(
                    self._throttle.max_available
                ),
                restore_rate=self._throttle.restore_rate,
                last_update_ts=(
                    self._throttle.last_update_ts
                ),
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "shop_url": self._shop,
                "api_version": self._version,
                "fallback_version": self._fallback,
                "calls": self._calls,
                "throttled_calls": self._throttled_calls,
                "throttle": self._throttle.as_dict(),
            }
