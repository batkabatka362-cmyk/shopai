"""TikTok Shop adapter — read-only foundation for Z6 mission.

Z6 (Competitive edge + Z6 mission): ShopAI's roadmap calls for
multi-platform sell beyond Shopify. TikTok Shop is the 2026
growth channel — unified cart + creator affiliate program +
Andromeda-grade AI ranking on the feed.

This module ships the *foundation*: HMAC request signer +
config check + two read-only calls (shop info, product list).
Writes (product create, order accept, fulfillment push) are
out of scope for this commit — each one adds real business
risk and needs its own tested wave.

API surface:

    adapter = TikTokShopAdapter()
    adapter.is_available()              # → bool
    adapter.fetch_shop_info()           # → TikTokShopShopInfo | None
    adapter.fetch_products(limit=50)    # → list[TikTokShopProduct]
    adapter.stats()                     # → diagnostics dict

Auth: TikTok Shop uses an HMAC-SHA256 signature over the
sorted-query-string + request-body convention documented at
developers.tiktok-shops.com. We implement ``_sign_request``
as a pure function so its behaviour is testable without
hitting the live API.

Required env:
  TIKTOK_SHOP_APP_KEY       (from developer console)
  TIKTOK_SHOP_APP_SECRET    (from developer console)
  TIKTOK_SHOP_ACCESS_TOKEN  (from OAuth install callback)
  TIKTOK_SHOP_SHOP_ID       (target shop's id)

Pure stdlib + requests-compatible http client. Thread-safe
via RLock. LLM-free.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from utils.logger import get_logger


logger = get_logger("core.adapters.tiktok_shop")


_DEFAULT_BASE = "https://open-api.tiktokglobalshop.com"
_DEFAULT_TIMEOUT = 10.0

_ENV_APP_KEY = "TIKTOK_SHOP_APP_KEY"
_ENV_APP_SECRET = "TIKTOK_SHOP_APP_SECRET"
_ENV_ACCESS_TOKEN = "TIKTOK_SHOP_ACCESS_TOKEN"
_ENV_SHOP_ID = "TIKTOK_SHOP_SHOP_ID"


@dataclass
class TikTokShopShopInfo:
    shop_id: str
    shop_name: str
    region: str = ""
    status: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "shop_id": self.shop_id,
            "shop_name": self.shop_name,
            "region": self.region,
            "status": self.status,
        }


@dataclass
class TikTokShopProduct:
    product_id: str
    title: str
    status: str = ""
    price_min: float = 0.0
    price_max: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "title": self.title,
            "status": self.status,
            "price_min": round(self.price_min, 2),
            "price_max": round(self.price_max, 2),
        }


def _sign_request(
    *,
    app_secret: str,
    path: str,
    params: dict[str, Any],
    body: str = "",
) -> str:
    """Compute the TikTok Shop HMAC-SHA256 signature.

    Algorithm (per developer docs):
      1. Collect every param except the ``sign`` itself
      2. Sort lexicographically by key
      3. Concatenate path + <key><value><key><value>...
      4. Append the request body if not empty
      5. Wrap in app_secret…app_secret
      6. HMAC-SHA256 keyed on app_secret, hex-encoded

    Pure function — deterministic for the same inputs.
    """
    if not app_secret:
        raise ValueError("app_secret required")
    ordered = sorted(
        (k, v) for k, v in params.items()
        if k not in ("sign", "access_token")
    )
    joined = "".join(
        f"{k}{v}" for k, v in ordered
    )
    payload = f"{path}{joined}"
    if body:
        payload = f"{payload}{body}"
    wrapped = f"{app_secret}{payload}{app_secret}"
    return hmac.new(
        app_secret.encode("utf-8"),
        wrapped.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class TikTokShopAdapter:
    """Read-only foundation for TikTok Shop integration."""

    name = "tiktok_shop"

    def __init__(
        self,
        *,
        app_key: str | None = None,
        app_secret: str | None = None,
        access_token: str | None = None,
        shop_id: str | None = None,
        base_url: str = _DEFAULT_BASE,
        http: Any = None,
        timeout: float = _DEFAULT_TIMEOUT,
        now_fn: Any = None,
    ) -> None:
        self._app_key = (
            app_key if app_key is not None
            else os.environ.get(_ENV_APP_KEY, "")
        )
        self._app_secret = (
            app_secret if app_secret is not None
            else os.environ.get(_ENV_APP_SECRET, "")
        )
        self._access_token = (
            access_token if access_token is not None
            else os.environ.get(_ENV_ACCESS_TOKEN, "")
        )
        self._shop_id = (
            shop_id if shop_id is not None
            else os.environ.get(_ENV_SHOP_ID, "")
        )
        self._base = base_url.rstrip("/")
        self._http = http
        self._timeout = float(timeout)
        self._now_fn = now_fn or time.time
        self._lock = threading.RLock()
        self._last_error = ""
        self._api_calls = 0

    def is_available(self) -> bool:
        return bool(
            self._app_key
            and self._app_secret
            and self._access_token
            and self._shop_id,
        )

    def _client(self) -> Any:
        if self._http is not None:
            return self._http
        import requests
        return requests

    def _request(
        self,
        path: str,
        *,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Signed GET to TikTok Shop. Returns parsed JSON on
        success, None on any failure (with ``_last_error``
        set for diagnostics)."""
        params: dict[str, Any] = {
            "app_key": self._app_key,
            "timestamp": str(int(self._now_fn())),
            "shop_id": self._shop_id,
            "access_token": self._access_token,
        }
        if extra_params:
            params.update({
                k: str(v) for k, v in extra_params.items()
            })
        params["sign"] = _sign_request(
            app_secret=self._app_secret,
            path=path,
            params=params,
        )
        url = (
            f"{self._base}{path}?"
            + urlencode(params)
        )
        try:
            resp = self._client().get(
                url, timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"network: {exc}"
            logger.debug("tiktok_shop %s: %s", path, exc)
            return None
        status = int(getattr(resp, "status_code", 0))
        if status >= 400:
            with self._lock:
                self._last_error = (
                    f"HTTP {status}: "
                    f"{(getattr(resp, 'text', '') or '')[:120]}"
                )
            return None
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"bad JSON: {exc}"
            return None
        if not isinstance(body, dict):
            with self._lock:
                self._last_error = (
                    "response not an object"
                )
            return None
        code = body.get("code")
        if code not in (0, None, "0"):
            with self._lock:
                self._last_error = (
                    f"api code {code}: "
                    f"{body.get('message', '')}"
                )
            return None
        with self._lock:
            self._api_calls += 1
            self._last_error = ""
        return body

    def fetch_shop_info(self) -> TikTokShopShopInfo | None:
        """GET /authorization/202309/shops — returns the
        first shop info, used as a health check."""
        if not self.is_available():
            with self._lock:
                self._last_error = (
                    "not configured — set "
                    f"{_ENV_APP_KEY}, {_ENV_APP_SECRET}, "
                    f"{_ENV_ACCESS_TOKEN}, {_ENV_SHOP_ID}"
                )
            return None
        body = self._request(
            "/authorization/202309/shops",
        )
        if body is None:
            return None
        data = body.get("data") or {}
        shops = data.get("shops") or []
        if not isinstance(shops, list) or not shops:
            return None
        first = shops[0] if isinstance(
            shops[0], dict,
        ) else {}
        return TikTokShopShopInfo(
            shop_id=str(first.get("id", "")),
            shop_name=str(first.get("name", "")),
            region=str(first.get("region", "")),
            status=str(first.get("status", "")),
            raw=dict(first),
        )

    def fetch_products(
        self, *, limit: int = 50,
    ) -> list[TikTokShopProduct]:
        """GET /product/202309/products/search — list of
        ``TikTokShopProduct``. Empty on any failure."""
        if not self.is_available():
            with self._lock:
                self._last_error = "not configured"
            return []
        capped = max(1, min(int(limit), 100))
        body = self._request(
            "/product/202309/products/search",
            extra_params={
                "page_size": capped,
                "page_number": 1,
            },
        )
        if body is None:
            return []
        data = body.get("data") or {}
        products = data.get("products") or []
        if not isinstance(products, list):
            return []
        out: list[TikTokShopProduct] = []
        for raw in products:
            if not isinstance(raw, dict):
                continue
            try:
                min_p = 0.0
                max_p = 0.0
                skus = raw.get("skus") or []
                if isinstance(skus, list) and skus:
                    prices = []
                    for sku in skus:
                        if isinstance(sku, dict):
                            p = sku.get("price", {})
                            if isinstance(p, dict):
                                try:
                                    prices.append(
                                        float(
                                            p.get(
                                                "sale_price",
                                                0,
                                            ) or 0,
                                        ),
                                    )
                                except (
                                    TypeError, ValueError,
                                ) as exc:
                                    logger.debug(
                                        "skip bad sku price: %s",
                                        exc,
                                    )
                    if prices:
                        min_p = min(prices)
                        max_p = max(prices)
                out.append(TikTokShopProduct(
                    product_id=str(raw.get("id", "")),
                    title=str(raw.get("title", "")),
                    status=str(raw.get("status", "")),
                    price_min=min_p,
                    price_max=max_p,
                    raw=dict(raw),
                ))
            except (TypeError, ValueError) as exc:
                logger.debug(
                    "skip malformed product: %s", exc,
                )
        return out

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "adapter": self.name,
                "configured": self.is_available(),
                "api_calls": self._api_calls,
                "last_error": self._last_error,
                "shop_id": self._shop_id,
            }
