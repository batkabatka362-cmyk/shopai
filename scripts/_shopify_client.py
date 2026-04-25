"""Shared Shopify Admin API client for Deguar operator scripts.

Consolidates the env-check + retry-aware HTTP wrapper that was
duplicated in ``deguar_live_audit.py``, ``deguar_bulk_images.py``,
and ``deguar_scope_audit.py``. Three copies means three places
to drift, so this is the canonical form.

Pure stdlib. No dependency on the rest of the core/ codebase so
it can be imported from ``scripts/`` without pulling the whole
app init chain.

Usage:

    from scripts._shopify_client import ShopifyClient

    client = ShopifyClient.from_env()
    products = client.get("products.json?limit=250")
    res = client.post("products/123/images.json", {"image": {"src": "..."}})
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class ShopifyClientMisconfigured(RuntimeError):
    """Raised when SHOPAI_SHOPIFY_URL / _KEY are missing.

    Callers usually want to print a friendly message + exit 2
    rather than propagate — see ``ShopifyClient.from_env_or_exit``.
    """


@dataclass(frozen=True)
class ShopifyClient:
    """Read + write wrapper around the Shopify 2024-10 Admin API.

    * ``url`` — bare host (``x.myshopify.com``), no scheme
    * ``token`` — ``shpat_...`` Admin API access token
    * ``api_version`` — default ``2024-10`` (stable per Shopify
      GA schedule; bump deliberately).
    * ``retries`` — number of retry attempts for 429 / 502 / 503.
    * ``throttle_s`` — sleep after every successful call. Shopify
      REST cap is 2 cps for standard apps, so 0 is fine for
      bursts; callers doing long loops should pass 0.5.
    """

    url: str
    token: str
    api_version: str = "2024-10"
    retries: int = 4
    throttle_s: float = 0.0

    @classmethod
    def from_env(cls, *, throttle_s: float = 0.0) -> "ShopifyClient":
        url = (os.environ.get("SHOPAI_SHOPIFY_URL") or "").strip()
        token = (
            os.environ.get("SHOPAI_SHOPIFY_KEY")
            or os.environ.get("SHOPAI_SHOPIFY_TOKEN")
            or ""
        ).strip()
        if not url or not token:
            raise ShopifyClientMisconfigured(
                "set SHOPAI_SHOPIFY_URL + SHOPAI_SHOPIFY_KEY in .env",
            )
        return cls(url=url, token=token, throttle_s=throttle_s)

    @classmethod
    def from_env_or_exit(
        cls, *, throttle_s: float = 0.0,
    ) -> "ShopifyClient":
        try:
            return cls.from_env(throttle_s=throttle_s)
        except ShopifyClientMisconfigured as exc:
            print(f"ERR: {exc}", file=sys.stderr)
            sys.exit(2)

    # ── Public HTTP surface ──────────────────────────────

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path, None)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, body)

    def put(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", path, body)

    def delete(self, path: str) -> dict[str, Any]:
        return self._request("DELETE", path, None)

    def oauth_get(self, path: str) -> dict[str, Any]:
        """Hit an endpoint under ``/admin/{path}`` (e.g.
        ``oauth/access_scopes.json``) — the few endpoints that
        live directly under ``/admin/`` and not under
        ``/admin/api/{version}/``."""
        return self._request_raw_admin("GET", path, None)

    # ── Internals ────────────────────────────────────────

    def _url(self, path: str) -> str:
        return (
            f"https://{self.url}/admin/api/{self.api_version}/{path}"
        )

    def _url_admin(self, path: str) -> str:
        return f"https://{self.url}/admin/{path}"

    def _request(
        self, method: str, path: str, body: dict | None,
    ) -> dict[str, Any]:
        return self._send(method, self._url(path), path, body)

    def _request_raw_admin(
        self, method: str, path: str, body: dict | None,
    ) -> dict[str, Any]:
        return self._send(
            method, self._url_admin(path), f"/admin/{path}", body,
        )

    def _send(
        self, method: str, full: str, label: str,
        body: dict | None,
    ) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "X-Shopify-Access-Token": self.token,
            "Accept": "application/json",
            "User-Agent": "ShopAI/deguar-scripts",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        last_exc: Exception | None = None

        for i in range(self.retries):
            try:
                req = urllib.request.Request(
                    full, data=data, headers=headers, method=method,
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read()
                    result = json.loads(raw) if raw else {}
                    if self.throttle_s > 0:
                        time.sleep(self.throttle_s)
                    return result
            except urllib.error.HTTPError as e:
                last_exc = e
                if e.code in (429, 502, 503) and i < self.retries - 1:
                    wait = 2 ** (i + 1)
                    sys.stderr.write(
                        f"  {e.code} on {method} {label} — "
                        f"retry in {wait}s\n",
                    )
                    time.sleep(wait)
                    continue
                raise
            except urllib.error.URLError as e:
                last_exc = e
                if i < self.retries - 1:
                    wait = 2 ** (i + 1)
                    sys.stderr.write(
                        f"  net err on {method} {label} — "
                        f"retry in {wait}s\n",
                    )
                    time.sleep(wait)
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError("retries exhausted")
