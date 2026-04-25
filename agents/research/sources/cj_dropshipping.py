"""CJDropshipping winner source — real 3rd-party product API.

Sprint 2 #5a. CJ Dropshipping (https://developers.cjdropshipping.com)
exposes an Open Platform API with trending + category endpoints. This
source hits their product list endpoint and maps each entry into a
``ProductCandidate``.

Auth: CJ issues an access token via an email/password exchange
(POST /api2.0/v1/authentication/getAccessToken). Owners set
``CJ_EMAIL`` + ``CJ_API_KEY`` (the "api key" in CJ's docs) in .env;
the source fetches + caches an access_token, refreshing on expiry.

Without credentials, ``is_available`` returns False so autopilot
silently skips this source.

Pure stdlib + requests.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Iterable

from agents.research.winner_searcher import (
    ProductCandidate, WinnerSource,
)
from utils.logger import get_logger


logger = get_logger("agents.research.sources.cj_dropshipping")


_DEFAULT_TIMEOUT = 20.0
_AUTH_PATH = "/api2.0/v1/authentication/getAccessToken"
_LIST_PATH = "/api2.0/v1/product/list"
_DEFAULT_BASE = "https://developers.cjdropshipping.com"
_TOKEN_LIFETIME_S = 6 * 3600  # 6 hours, CJ docs say 7d but be safe


class CJDropshippingSource(WinnerSource):
    """CJ Dropshipping API product feed as a WinnerSource."""

    name = "cj_dropshipping"

    def __init__(
        self,
        *,
        email: str = "",
        api_key: str = "",
        base_url: str = _DEFAULT_BASE,
        per_fetch_limit: int = 50,
        category_id: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
        http: Any = None,
        cost_margin_ratio: float = 2.5,
    ) -> None:
        """``cost_margin_ratio`` is the retail / cost multiplier we
        assume when CJ returns only sell_price. Default 2.5× means
        a $10 CJ product implies $25 retail, 60% margin. Conservative.
        """
        self._email = (
            email or os.environ.get("CJ_EMAIL", "")
        )
        self._api_key = (
            api_key or os.environ.get("CJ_API_KEY", "")
        )
        self._base = base_url.rstrip("/")
        self._limit = int(per_fetch_limit)
        self._category_id = str(category_id or "")
        self._timeout = float(timeout)
        self._http = http
        self._margin_ratio = float(cost_margin_ratio)
        self._lock = threading.Lock()
        self._token: str = ""
        self._token_expiry: float = 0.0
        self._last_error: str = ""
        self._last_fetch_count: int = 0

    def is_available(self) -> bool:
        return bool(self._email) and bool(self._api_key)

    # ── HTTP plumbing ────────────────────────────────────

    def _client(self) -> Any:
        if self._http is not None:
            return self._http
        import requests
        return requests

    def _ensure_token(self) -> str:
        now = time.time()
        with self._lock:
            if (
                self._token
                and now < self._token_expiry
            ):
                return self._token
        url = f"{self._base}{_AUTH_PATH}"
        body = {
            "email": self._email,
            "password": self._api_key,
        }
        try:
            resp = self._client().post(
                url, json=body, timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"CJ auth network error: {exc}",
            ) from exc
        if resp.status_code >= 400:
            raise RuntimeError(
                f"CJ auth HTTP {resp.status_code}: "
                f"{resp.text[:200]}",
            )
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"CJ auth non-JSON: {exc}",
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError("CJ auth: unexpected shape")
        payload = data.get("data") or {}
        token = (
            payload.get("accessToken")
            or data.get("accessToken")
            or ""
        )
        if not token:
            msg = str(
                data.get("message") or "no token",
            )
            raise RuntimeError(f"CJ auth: {msg}")
        with self._lock:
            self._token = str(token)
            self._token_expiry = (
                time.time() + _TOKEN_LIFETIME_S
            )
        return self._token

    # ── Fetch ────────────────────────────────────────────

    def fetch(
        self, *, limit: int = 100,
    ) -> list[ProductCandidate]:
        if not self.is_available():
            with self._lock:
                self._last_error = (
                    "CJ credentials missing (set "
                    "CJ_EMAIL + CJ_API_KEY)"
                )
            return []
        take = min(int(limit), self._limit)
        try:
            token = self._ensure_token()
        except Exception as exc:  # noqa: BLE001
            logger.debug("CJ token fetch failed: %s", exc)
            with self._lock:
                self._last_error = str(exc)
            return []
        params = {
            "pageNum": 1,
            "pageSize": take,
        }
        if self._category_id:
            params["categoryId"] = self._category_id
        url = f"{self._base}{_LIST_PATH}"
        try:
            resp = self._client().get(
                url, params=params,
                headers={
                    "CJ-Access-Token": token,
                    "Accept": "application/json",
                },
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "CJ list fetch network error: %s", exc,
            )
            with self._lock:
                self._last_error = (
                    f"network error: {exc}"
                )
            return []
        if resp.status_code >= 400:
            with self._lock:
                self._last_error = (
                    f"HTTP {resp.status_code}"
                )
            return []
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = (
                    f"non-JSON: {exc}"
                )
            return []
        items = (
            ((payload or {}).get("data") or {})
            .get("list") or []
        )
        out: list[ProductCandidate] = []
        for item in items[: take]:
            candidate = self._to_candidate(item)
            if candidate is not None:
                out.append(candidate)
        with self._lock:
            self._last_fetch_count = len(out)
            self._last_error = ""
        return out

    def _to_candidate(
        self, item: dict[str, Any],
    ) -> ProductCandidate | None:
        if not isinstance(item, dict):
            return None
        title = str(
            item.get("productNameEn")
            or item.get("productName")
            or "",
        ).strip()
        if not title:
            return None
        # CJ returns "sellPrice" as string with currency; normalise
        raw_cost = item.get("sellPrice") or ""
        try:
            cost = float(
                str(raw_cost).replace("$", "").strip(),
            )
        except (TypeError, ValueError):
            cost = 0.0
        price = round(
            cost * self._margin_ratio, 2,
        ) if cost > 0 else 0.0
        ext_id = str(item.get("productId", "")).strip()
        if not ext_id:
            return None
        image_url = str(
            item.get("productImage") or "",
        )
        product_url = (
            item.get("productUrl") or "").strip()
        if not product_url:
            product_url = (
                f"https://cjdropshipping.com/product/"
                f"{ext_id}.html"
            )
        tags_raw = item.get("categoryName") or ""
        tags = (
            (str(tags_raw).strip(),)
            if tags_raw else ()
        )
        sold = item.get("listedNum") or 0
        try:
            listed_num = int(sold)
        except (TypeError, ValueError):
            listed_num = 0
        # CJ doesn't expose true daily_sales; listed_num is a peer-
        # count proxy — log-compressed into a 0-50 band
        import math
        daily_sales = float(
            min(
                50.0,
                math.log1p(listed_num) * 5.0,
            ),
        )
        return ProductCandidate(
            source="cj_dropshipping",
            external_id=ext_id,
            title=title,
            price=price,
            cost=cost,
            daily_sales=daily_sales,
            saturation_score=0.5,
            image_url=image_url,
            url=product_url,
            tags=tags,
            raw=dict(item),
        )

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "configured": self.is_available(),
                "has_token": bool(self._token),
                "token_expires_in": max(
                    0.0,
                    self._token_expiry - time.time(),
                ) if self._token else 0.0,
                "last_fetch_count": self._last_fetch_count,
                "last_error": self._last_error,
            }
