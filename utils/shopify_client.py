"""Shared Shopify Admin REST API client.

Replaces the duplicated _api_get / _api_post / _api_put helpers that
lived in store_cloner.py and store_configurator.py (and similar places).
Provides:

- Retry on transient HTTP 429 / 5xx with exponential backoff
- Consistent error handling — returns {"error": ...} rather than {}
  so callers can distinguish "no data" from "call failed"
- Automatic rate limiting via a token bucket (40 req/s per app budget,
  default 10 req/s to leave headroom)
- Thread-safe (urllib is stateless, bucket uses a lock)
- Single configuration point for API version

Usage:
    client = ShopifyClient("mystore.myshopify.com", token)
    products = client.get("products.json", params={"limit": 50})
    client.post("pages.json", json={"page": {...}})
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("shopify.client")


API_VERSION = "2024-01"

# Safe default: stay well under Shopify's 40 req/s bucket
_DEFAULT_RATE_LIMIT = 10.0

# Retry config for transient failures
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 3
_RETRY_DELAYS = (0.5, 1.5, 4.0)  # seconds


class _TokenBucket:
    """Simple token-bucket rate limiter shared across threads."""

    def __init__(self, rate_per_sec: float, burst: int = 5) -> None:
        self._rate = rate_per_sec
        self._capacity = max(1, burst)
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def take(self) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Wait for enough tokens
                need = 1.0 - self._tokens
                wait = need / self._rate
            time.sleep(wait)


class ShopifyClient:
    """Admin REST API client for a single store."""

    def __init__(
        self,
        shop_url: str,
        access_token: str,
        *,
        api_version: str = API_VERSION,
        rate_limit: float = _DEFAULT_RATE_LIMIT,
        timeout: float = 15.0,
    ) -> None:
        self._shop_url = shop_url.strip("/")
        self._token = access_token
        self._api_version = api_version
        self._timeout = timeout
        self._bucket = _TokenBucket(rate_limit)

    @property
    def shop_url(self) -> str:
        return self._shop_url

    # ── Public methods ─────────────────────────────────────────

    def get(self, path: str, *, params: Optional[dict] = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, *, json: Optional[dict] = None) -> dict[str, Any]:
        return self._request("POST", path, json_body=json)

    def put(self, path: str, *, json: Optional[dict] = None) -> dict[str, Any]:
        return self._request("PUT", path, json_body=json)

    def delete(self, path: str) -> dict[str, Any]:
        return self._request("DELETE", path)

    # ── Internal ───────────────────────────────────────────────

    def _build_url(self, path: str, params: Optional[dict]) -> str:
        base = f"https://{self._shop_url}/admin/api/{self._api_version}/{path.lstrip('/')}"
        if params:
            query = urllib.parse.urlencode(params)
            sep = "&" if "?" in base else "?"
            base = f"{base}{sep}{query}"
        return base

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> dict[str, Any]:
        url = self._build_url(path, params)
        headers = {
            "X-Shopify-Access-Token": self._token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")

        last_error: str = ""
        for attempt in range(_MAX_RETRIES + 1):
            self._bucket.take()
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    body = resp.read()
                    if not body:
                        return {}
                    try:
                        return json.loads(body)
                    except json.JSONDecodeError:
                        return {"error": "invalid JSON response", "body": body[:200].decode("utf-8", errors="replace")}
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:300] if hasattr(exc, "read") else ""
                last_error = f"HTTP {exc.code}: {body}"
                if exc.code in _RETRY_STATUS and attempt < _MAX_RETRIES:
                    delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                    logger.warning(
                        "Shopify %s %s → HTTP %d, retry %d/%d in %.1fs",
                        method, path, exc.code, attempt + 1, _MAX_RETRIES, delay,
                    )
                    time.sleep(delay)
                    continue
                logger.warning("Shopify %s %s failed: %s", method, path, last_error)
                return {"error": last_error, "status_code": exc.code}
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                    time.sleep(delay)
                    continue
                logger.warning("Shopify %s %s failed: %s", method, path, last_error)
                return {"error": last_error}

        return {"error": last_error or "unknown"}
