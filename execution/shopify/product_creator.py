"""ProductCreator — creates products via the Shopify REST Admin API.

Uses only the Python standard library (urllib.request / urllib.error).
Optional third-party HTTP libraries are accepted if available but not required.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


_REQUIRED_FIELDS = ("title", "price", "description")


class ProductCreator:
    """Creates single and bulk products on a Shopify store."""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def create_product(
        self,
        shop_url: str,
        api_key: str,
        product_data: dict[str, Any],
    ) -> dict[str, Any]:
        """POST a new product to the Shopify REST API.

        Args:
            shop_url:     e.g. ``"mystore.myshopify.com"``
            api_key:      Shopify Admin API access token / password.
            product_data: Raw product fields (title, price, description, …).

        Returns:
            The created product dict as returned by Shopify, wrapped in a
            ``{"product": …, "status": "created"}`` envelope on success, or
            ``{"error": …, "status": "error"}`` on failure.
        """
        errors = self._validate_product(product_data)
        if errors:
            return {"status": "error", "errors": errors}

        payload = self._format_product_payload(product_data)
        url = self._build_url(shop_url, "/admin/api/2024-01/products.json")
        headers = self._build_headers(api_key)

        try:
            response = self._make_request("POST", url, headers, payload)
            return {"status": "created", "product": response.get("product", response)}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def create_bulk(
        self,
        shop_url: str,
        api_key: str,
        products: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create multiple products sequentially, collecting results and errors.

        Returns:
            ``{"results": [...], "errors": [...], "total": N,
               "succeeded": N, "failed": N}``
        """
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for idx, product_data in enumerate(products):
            result = self.create_product(shop_url, api_key, product_data)
            if result.get("status") == "created":
                results.append(result)
            else:
                errors.append({"index": idx, "product": product_data, "error": result})

        return {
            "results": results,
            "errors": errors,
            "total": len(products),
            "succeeded": len(results),
            "failed": len(errors),
        }

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _validate_product(self, product_data: dict[str, Any]) -> list[str]:
        """Return a list of validation error messages (empty = valid)."""
        errs: list[str] = []
        for field in _REQUIRED_FIELDS:
            if not product_data.get(field):
                errs.append(f"Missing required field: '{field}'")

        price = product_data.get("price")
        if price is not None:
            try:
                if float(price) < 0:
                    errs.append("Field 'price' must be non-negative.")
            except (TypeError, ValueError):
                errs.append("Field 'price' must be a numeric value.")

        return errs

    def _format_product_payload(self, product_data: dict[str, Any]) -> dict[str, Any]:
        """Convert flat product_data into the Shopify product JSON shape."""
        price = str(product_data.get("price", "0.00"))

        variants = product_data.get("variants")
        if not variants:
            variants = [
                {
                    "price": price,
                    "inventory_management": product_data.get(
                        "inventory_management", "shopify"
                    ),
                    "inventory_quantity": int(
                        product_data.get("inventory_quantity", 0)
                    ),
                    "sku": product_data.get("sku", ""),
                    "weight": product_data.get("weight", 0),
                    "weight_unit": product_data.get("weight_unit", "kg"),
                }
            ]

        images = product_data.get("images", [])
        if isinstance(images, list) and images and isinstance(images[0], str):
            # Accept a plain list of URLs
            images = [{"src": url} for url in images]

        payload: dict[str, Any] = {
            "title": product_data["title"],
            "body_html": product_data.get("description", ""),
            "vendor": product_data.get("vendor", ""),
            "product_type": product_data.get("product_type", ""),
            "tags": product_data.get("tags", ""),
            "status": product_data.get("status", "active"),
            "variants": variants,
            "images": images,
        }

        # Pass through any extra top-level keys the caller provided
        for k, v in product_data.items():
            if k not in payload and k not in (
                "price", "sku", "weight", "weight_unit",
                "inventory_quantity", "inventory_management",
            ):
                payload[k] = v

        return {"product": payload}

    def _make_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform an HTTP request using urllib.request.

        Handles 429 Too Many Requests with exponential back-off (up to 3
        retries).  Raises ``urllib.error.HTTPError`` for other 4xx/5xx codes.
        """
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
                # Re-raise with body for better diagnostics
                body = exc.read().decode("utf-8", errors="replace")
                raise urllib.error.HTTPError(
                    url, exc.code, f"{exc.reason} — {body}", exc.headers, None
                ) from exc
            except urllib.error.URLError as exc:
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise

        raise RuntimeError(f"Request to {url} failed after {max_retries} retries.")

    # ------------------------------------------------------------------ #
    # Internal utilities                                                   #
    # ------------------------------------------------------------------ #

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
