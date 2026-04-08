"""ShopifyAPI — fetches products, orders, and customers from the Shopify REST Admin API."""
from __future__ import annotations

import datetime
import email.utils
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


def _normalize_shop_url(raw: str) -> str:
    """Strip scheme / trailing slashes from a Shopify shop URL.

    Accepts any of::

        mystore.myshopify.com
        https://mystore.myshopify.com
        https://mystore.myshopify.com/
        http://mystore.myshopify.com/

    Returns the bare host component. Pre-audit the client did
    ``f"https://{shop_url.rstrip('/')}/admin/..."`` which
    produced ``https://https://mystore.myshopify.com/admin/...``
    when the caller passed a scheme-prefixed URL. Audit pass 43.
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip().rstrip("/")
    if s.startswith("https://"):
        s = s[len("https://"):]
    elif s.startswith("http://"):
        s = s[len("http://"):]
    return s


def _parse_retry_after(header: str, fallback: float) -> float:
    """Parse an HTTP ``Retry-After`` header.

    RFC 7231 allows either a delta-seconds number OR an HTTP-date
    string (e.g. ``"Wed, 21 Oct 2015 07:28:00 GMT"``). Pre-audit
    the client did ``float(header)`` which crashed with ValueError
    whenever Shopify (or a CDN in front of it) returned the
    date form. Audit pass 43.
    """
    if not isinstance(header, str) or not header:
        return fallback
    # Try delta-seconds first.
    try:
        return max(0.0, float(header))
    except ValueError:
        pass
    # Fall back to HTTP-date parsing.
    try:
        dt = email.utils.parsedate_to_datetime(header)
        if dt is None:
            return fallback
        now = datetime.datetime.now(datetime.timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        delta = (dt - now).total_seconds()
        return max(0.0, delta) if delta > 0 else fallback
    except (TypeError, ValueError):
        return fallback


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
                      Any leading ``https://`` / ``http://`` scheme is
                      stripped automatically — pre-audit a scheme-prefixed
                      URL produced ``https://https://...`` in the
                      request target.
            api_key:  Private-app admin API access token.
        """
        self._shop_url = _normalize_shop_url(shop_url)
        self._api_key = api_key if isinstance(api_key, str) else ""

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
        if not isinstance(days_back, int) or days_back <= 0:
            days_back = 30

        url_base, headers = self._resolve_credentials(shop_url, api_key)
        endpoint = f"{url_base}/orders.json"

        # Use timezone-aware UTC now. ``datetime.utcnow()`` is
        # deprecated in Python 3.12+ (DeprecationWarning → removal).
        # Audit pass 43.
        since_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_back)
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
        # Normalise EVERY time — the per-call override path can
        # still receive a scheme-prefixed URL. Audit pass 43.
        url = _normalize_shop_url(shop_url) or self._shop_url
        key = api_key if isinstance(api_key, str) and api_key else self._api_key
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
            # Pre-audit this returned ``[]`` silently, so callers
            # couldn't tell a missing-dependency environment from
            # a successful empty fetch. Raise the same error the
            # retry path raises so the caller's try/except records
            # it in the ``errors`` list. Audit pass 43.
            raise ShopifyAPIError(
                "requests library not available; install 'requests' to use ShopifyAPI"
            )

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
            try:
                payload = response.json()
            except ValueError as exc:
                raise ShopifyAPIError(f"Invalid JSON from Shopify: {exc}") from exc
            if not isinstance(payload, dict):
                raise ShopifyAPIError(
                    f"Expected JSON object from Shopify, got {type(payload).__name__}"
                )
            records = payload.get(resource_key) or []
            if not isinstance(records, list):
                records = []
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
        if not isinstance(max_retries, int) or max_retries < 1:
            max_retries = 1
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = _requests.get(url, headers=headers, params=params, timeout=30)
                if resp.status_code == 429:
                    # ``Retry-After`` can be either a delta-seconds
                    # int OR an HTTP-date string per RFC 7231. Pre-
                    # audit ``float(resp.headers.get("Retry-After"))``
                    # crashed on the date form. Audit pass 43.
                    wait = _parse_retry_after(
                        resp.headers.get("Retry-After", ""),
                        retry_delay * attempt,
                    )
                    logger.warning("Rate-limited; sleeping %.1fs (attempt %d)", wait, attempt)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(retry_delay * attempt)
        raise ShopifyAPIError(
            f"Request failed after {max_retries} attempts: {last_exc}"
        )

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
