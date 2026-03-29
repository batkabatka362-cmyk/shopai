"""ShopifyAPI — fetches products, orders, and customers from the Shopify REST Admin API."""
from __future__ import annotations

import time
import logging
from typing import Any

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = logging.getLogger("data_pipeline.shopify_api")


class ShopifyAPIError(Exception):
    """Raised when the Shopify API returns a non-successful response."""


class ShopifyAPI:
    """Fetches structured data from a Shopify store via the Admin REST API (2024-01)."""

    _API_VERSION = "2024-01"
    _DEFAULT_LIMIT = 250  # maximum page size allowed by Shopify

    def __init__(self, shop_url: str = "", api_key: str = "") -> None:
        """
        Args:
            shop_url: Shopify store domain, e.g. ``mystore.myshopify.com``.
            api_key:  Private-app admin API access token.
        """
        self._shop_url = shop_url.rstrip("/")
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_products(self, shop_url: str = "", api_key: str = "") -> dict[str, Any]:
        """Return all published products for the store.

        Args:
            shop_url: Override the instance-level shop URL.
            api_key:  Override the instance-level API key.

        Returns:
            ``{"products": [...], "total": int, "errors": [...]}``
        """
        url_base, headers = self._resolve_credentials(shop_url, api_key)
        endpoint = f"{url_base}/products.json"
        params: dict[str, Any] = {"limit": self._DEFAULT_LIMIT, "status": "active"}

        products: list[dict[str, Any]] = []
        errors: list[str] = []

        try:
            products = self._paginate(endpoint, headers, params, "products")
        except Exception as exc:  # noqa: BLE001
            logger.error("fetch_products failed: %s", exc)
            errors.append(str(exc))

        return {"products": products, "total": len(products), "errors": errors}

    def fetch_orders(
        self,
        shop_url: str = "",
        api_key: str = "",
        days_back: int = 30,
    ) -> dict[str, Any]:
        """Return orders created within the last *days_back* days.

        Args:
            shop_url:  Override the instance-level shop URL.
            api_key:   Override the instance-level API key.
            days_back: How many days of history to retrieve (default 30).

        Returns:
            ``{"orders": [...], "total": int, "errors": [...]}``
        """
        import datetime

        url_base, headers = self._resolve_credentials(shop_url, api_key)
        endpoint = f"{url_base}/orders.json"

        since_dt = datetime.datetime.utcnow() - datetime.timedelta(days=days_back)
        since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        params: dict[str, Any] = {
            "limit": self._DEFAULT_LIMIT,
            "status": "any",
            "created_at_min": since_iso,
        }

        orders: list[dict[str, Any]] = []
        errors: list[str] = []

        try:
            orders = self._paginate(endpoint, headers, params, "orders")
        except Exception as exc:  # noqa: BLE001
            logger.error("fetch_orders failed: %s", exc)
            errors.append(str(exc))

        return {"orders": orders, "total": len(orders), "errors": errors}

    def fetch_customers(self, shop_url: str = "", api_key: str = "") -> dict[str, Any]:
        """Return all customers for the store.

        Returns:
            ``{"customers": [...], "total": int, "errors": [...]}``
        """
        url_base, headers = self._resolve_credentials(shop_url, api_key)
        endpoint = f"{url_base}/customers.json"
        params: dict[str, Any] = {"limit": self._DEFAULT_LIMIT}

        customers: list[dict[str, Any]] = []
        errors: list[str] = []

        try:
            customers = self._paginate(endpoint, headers, params, "customers")
        except Exception as exc:  # noqa: BLE001
            logger.error("fetch_customers failed: %s", exc)
            errors.append(str(exc))

        return {"customers": customers, "total": len(customers), "errors": errors}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_credentials(
        self, shop_url: str, api_key: str
    ) -> tuple[str, dict[str, str]]:
        """Return the resolved (base_url, headers) pair."""
        url = (shop_url or self._shop_url).rstrip("/")
        key = api_key or self._api_key
        base = f"https://{url}/admin/api/{self._API_VERSION}"
        return base, self._build_headers(key)

    def _build_headers(self, api_key: str) -> dict[str, str]:
        """Build HTTP headers for Shopify Admin API requests."""
        return {
            "X-Shopify-Access-Token": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _paginate(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any],
        resource_key: str,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> list[dict[str, Any]]:
        """Fetch all pages of a Shopify cursor-paginated endpoint.

        Shopify uses ``Link`` headers with ``rel="next"`` cursors.
        """
        if not _REQUESTS_AVAILABLE:
            logger.warning("requests library not available; returning empty list")
            return []

        all_records: list[dict[str, Any]] = []
        next_url: str | None = url

        while next_url:
            response = self._get_with_retry(
                next_url,
                headers,
                params if next_url == url else None,
                max_retries,
                retry_delay,
            )
            payload = response.json()
            records = payload.get(resource_key, [])
            all_records.extend(records)
            logger.debug(
                "Fetched %d %s (running total: %d)",
                len(records),
                resource_key,
                len(all_records),
            )

            next_url = self._extract_next_link(response.headers.get("Link", ""))

        return all_records

    def _get_with_retry(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        max_retries: int,
        retry_delay: float,
    ):  # type: ignore[return]
        """Perform a GET with exponential-backoff retry on 429/5xx."""
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = _requests.get(url, headers=headers, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", retry_delay * attempt))
                    logger.warning("Rate-limited; sleeping %.1fs (attempt %d)", wait, attempt)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(retry_delay * attempt)
        raise ShopifyAPIError(f"Request failed after {max_retries} attempts: {last_exc}")

    @staticmethod
    def _extract_next_link(link_header: str) -> str | None:
        """Parse the ``Link`` header and return the ``next`` URL, or ``None``."""
        if not link_header:
            return None
        for part in link_header.split(","):
            segments = [s.strip() for s in part.split(";")]
            if len(segments) == 2 and segments[1] == 'rel="next"':
                return segments[0].strip("<>")
        return None
