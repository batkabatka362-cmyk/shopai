"""StoreManager — manages Shopify store info, settings, and collections.

Uses only the Python standard library (urllib.request / urllib.error).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class StoreManager:
    """Read and update store-level resources on a Shopify store."""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_store_info(self, shop_url: str, api_key: str) -> dict[str, Any]:
        """Fetch shop metadata (name, email, currency, plan, etc.).

        Returns:
            ``{"status": "ok", "shop": {...}}`` or error dict.
        """
        url = self._build_url(shop_url, "/admin/api/2024-01/shop.json")
        headers = self._build_headers(api_key)
        try:
            response = self._make_request("GET", url, headers)
            return {"status": "ok", "shop": response.get("shop", response)}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def update_store_settings(
        self,
        shop_url: str,
        api_key: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """Partially update store settings via the Shop resource.

        Only a limited set of fields are editable (e.g. ``email``,
        ``customer_email``, ``google_apps_domain``).  Shopify will silently
        ignore read-only fields.

        Returns:
            ``{"status": "updated", "shop": {...}}`` or error dict.
        """
        url = self._build_url(shop_url, "/admin/api/2024-01/shop.json")
        headers = self._build_headers(api_key)
        payload = {"shop": settings}
        try:
            response = self._make_request("PUT", url, headers, payload)
            return {"status": "updated", "shop": response.get("shop", response)}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def create_collection(
        self,
        shop_url: str,
        api_key: str,
        collection_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new custom collection.

        *collection_data* should include at least ``title``.  Optional fields:
        ``body_html``, ``image``, ``sort_order``, ``published``.

        Returns:
            ``{"status": "created", "collection": {...}}`` or error dict.
        """
        url = self._build_url(shop_url, "/admin/api/2024-01/custom_collections.json")
        headers = self._build_headers(api_key)
        payload = {"custom_collection": collection_data}
        try:
            response = self._make_request("POST", url, headers, payload)
            collection = response.get(
                "custom_collection", response.get("collection", response)
            )
            return {"status": "created", "collection": collection}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def add_products_to_collection(
        self,
        shop_url: str,
        api_key: str,
        collection_id: str | int,
        product_ids: list[str | int],
    ) -> dict[str, Any]:
        """Add products to a custom collection by creating collects.

        One ``POST /collects.json`` request is issued per product.

        Returns:
            ``{"status": "ok", "added": [...], "errors": [...]}``
        """
        added: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        url = self._build_url(shop_url, "/admin/api/2024-01/collects.json")
        headers = self._build_headers(api_key)

        for product_id in product_ids:
            payload = {
                "collect": {
                    "product_id": product_id,
                    "collection_id": collection_id,
                }
            }
            try:
                response = self._make_request("POST", url, headers, payload)
                added.append(response.get("collect", {"product_id": product_id}))
            except Exception as exc:
                errors.append({"product_id": product_id, "error": str(exc)})

        return {
            "status": "ok" if not errors else "partial",
            "added": added,
            "errors": errors,
            "collection_id": collection_id,
        }

    def get_store_stats(self, shop_url: str, api_key: str) -> dict[str, Any]:
        """Return high-level counts: orders, products, customers.

        Makes three lightweight ``count`` API calls in sequence.

        Returns:
            ``{"status": "ok", "order_count": N, "product_count": N,
               "customer_count": N}`` or error dict.
        """
        headers = self._build_headers(api_key)
        stats: dict[str, Any] = {"status": "ok"}
        endpoints = {
            "order_count": "/admin/api/2024-01/orders/count.json?status=any",
            "product_count": "/admin/api/2024-01/products/count.json",
            "customer_count": "/admin/api/2024-01/customers/count.json",
        }
        errors: list[str] = []
        for key, path in endpoints.items():
            url = self._build_url(shop_url, path)
            try:
                response = self._make_request("GET", url, headers)
                stats[key] = response.get("count", 0)
            except Exception as exc:
                stats[key] = None
                errors.append(f"{key}: {exc}")

        if errors:
            stats["status"] = "partial"
            stats["errors"] = errors
        return stats

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _make_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """HTTP request via urllib with 429 retry and exponential back-off."""
        data: bytes | None = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers = {**headers, "Content-Type": "application/json"}

        max_retries = 3
        delay = 1.0

        for attempt in range(max_retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8")
                    return json.loads(body) if body else {}
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < max_retries:
                    retry_after = float(exc.headers.get("Retry-After", delay))
                    time.sleep(retry_after)
                    delay *= 2
                    continue
                body = exc.read().decode("utf-8", errors="replace")
                raise urllib.error.HTTPError(
                    url, exc.code, f"{exc.reason} — {body}", exc.headers, None
                ) from exc
            except urllib.error.URLError:
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise

        raise RuntimeError(f"Request to {url} failed after {max_retries} retries.")

    @staticmethod
    def _build_url(shop_url: str, path: str) -> str:
        host = shop_url.rstrip("/")
        if not host.startswith("http"):
            host = f"https://{host}"
        return f"{host}{path}"

    @staticmethod
    def _build_headers(api_key: str) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": api_key,
            "Accept": "application/json",
        }
