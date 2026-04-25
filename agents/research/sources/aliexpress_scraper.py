"""AliExpress scraper — experimental winner source.

Sprint 2 #5b. AliExpress doesn't expose a free public API for
trending products. Their affiliate API ("AliExpress Dropshipping
Open Platform") requires partner approval. For owners without that
access, this module offers a best-effort JSON scraper that parses
publicly-reachable ``search`` + ``item`` responses.

**Fragility warning:** AliExpress aggressively rotates their anti-
bot defence. This source is marked *experimental*:
``experimental = True`` and ``is_available`` returns False unless
the ``SHOPAI_ENABLE_ALIEXPRESS_SCRAPER=1`` env gate is set. Even
when enabled, a parse failure degrades silently (empty list +
last_error populated).

For production winner discovery use:
  * CJDropshippingSource (real API)
  * ManualSeedSource (owner-curated)
  * PeerStoreObserverSource (public /products.json)

This source exists because the owner asked for *all* sources to be
real. It's a skeleton wired so a proper scraping implementation
(Playwright / rotating user agents / proxy pool) can be dropped in
without touching WinnerSearcher.

Pure stdlib + requests.
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from typing import Any, Iterable

from agents.research.winner_searcher import (
    ProductCandidate, WinnerSource,
)
from utils.logger import get_logger


logger = get_logger("agents.research.sources.aliexpress_scraper")


_ENABLE_ENV = "SHOPAI_ENABLE_ALIEXPRESS_SCRAPER"
_DEFAULT_TIMEOUT = 20.0
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)


class AliExpressScraperSource(WinnerSource):
    """Experimental AliExpress winner source.

    This implementation uses AliExpress's public search endpoint
    which returns semi-structured JSON within an HTML shell. Anti-
    bot protection frequently changes the extraction path; parsing
    failures are tolerated silently.

    Activation: set ``SHOPAI_ENABLE_ALIEXPRESS_SCRAPER=1``.
    """

    name = "aliexpress_scraper"
    experimental = True

    def __init__(
        self,
        *,
        query: str = "",
        per_fetch_limit: int = 20,
        timeout: float = _DEFAULT_TIMEOUT,
        http: Any = None,
        enable_override: bool | None = None,
        user_agent: str = _DEFAULT_USER_AGENT,
    ) -> None:
        self._query = str(query)
        self._limit = int(per_fetch_limit)
        self._timeout = float(timeout)
        self._http = http
        self._user_agent = str(user_agent)
        # override primarily for tests; default checks env gate
        self._enable = (
            bool(enable_override)
            if enable_override is not None
            else os.environ.get(_ENABLE_ENV, "") == "1"
        )
        self._lock = threading.Lock()
        self._last_fetch_count = 0
        self._last_error = ""

    def is_available(self) -> bool:
        return bool(self._enable)

    # ── Fetch ────────────────────────────────────────────

    def fetch(
        self, *, limit: int = 100,
    ) -> list[ProductCandidate]:
        if not self.is_available():
            with self._lock:
                self._last_error = (
                    f"scraper disabled "
                    f"(set {_ENABLE_ENV}=1 to opt in)"
                )
            return []
        take = min(int(limit), self._limit)
        url = self._build_url()
        try:
            body = self._fetch_html(url)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "aliexpress scraper fetch failed: %s",
                exc,
            )
            with self._lock:
                self._last_error = str(exc)
            return []
        products = self._parse_items(body, limit=take)
        with self._lock:
            self._last_fetch_count = len(products)
            if not products:
                self._last_error = (
                    "no products parsed — AliExpress "
                    "may have changed shape"
                )
            else:
                self._last_error = ""
        return products

    def _build_url(self) -> str:
        base = "https://www.aliexpress.com/wholesale"
        q = self._query or "trending"
        # Simple URL — the real scraper should add region, currency,
        # and anti-bot hints; left minimal to keep skeleton honest.
        return (
            f"{base}?SearchText={q.replace(' ', '+')}"
        )

    def _fetch_html(self, url: str) -> str:
        client = self._http
        if client is None:
            import requests
            client = requests
        resp = client.get(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"HTTP {resp.status_code}",
            )
        return resp.text or ""

    def _parse_items(
        self, html: str, *, limit: int,
    ) -> list[ProductCandidate]:
        """Best-effort AliExpress JSON extraction.

        AliExpress embeds ``window._dida_config_._init_data_`` with
        a JSON payload containing search results. Shape drifts
        often; we pull title + price + image + link with regex
        fallbacks and tolerate failures.
        """
        if not html:
            return []
        # Primary path: window.runParams
        match = re.search(
            r"window\.runParams\s*=\s*"
            r"({.*?});?\s*</script>",
            html, flags=re.DOTALL,
        )
        if match:
            try:
                import json
                payload = json.loads(match.group(1))
                items = (
                    (payload or {}).get("mods", {})
                    .get("itemList", {})
                    .get("content", [])
                    or []
                )
                return self._normalise_items(
                    items, limit=limit,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "aliexpress runParams parse "
                    "failed: %s",
                    exc,
                )
        # Fallback: regex over visible product cards
        products: list[ProductCandidate] = []
        for hit in re.finditer(
            r'data-product-id="(\d+)"[^>]*'
            r'data-title="([^"]+)"[^>]*'
            r'data-price="([\d.]+)"',
            html,
        ):
            pid, title, price_s = hit.groups()
            try:
                price = float(price_s)
            except ValueError:
                continue
            products.append(
                ProductCandidate(
                    source="aliexpress_scraper",
                    external_id=str(pid),
                    title=str(title),
                    price=price,
                    cost=price * 0.4,    # assume 60% margin
                    daily_sales=5.0,
                    saturation_score=0.6,
                    image_url="",
                    url=(
                        f"https://www.aliexpress.com/"
                        f"item/{pid}.html"
                    ),
                    tags=(),
                ),
            )
            if len(products) >= limit:
                break
        return products

    def _normalise_items(
        self,
        items: list[Any],
        *,
        limit: int,
    ) -> list[ProductCandidate]:
        out: list[ProductCandidate] = []
        for item in items[: limit]:
            if not isinstance(item, dict):
                continue
            title = str(
                item.get("title", {})
                if isinstance(item.get("title"), dict)
                else item.get("title") or "",
            ).strip()
            if isinstance(item.get("title"), dict):
                title = str(
                    item["title"].get("displayTitle", "")
                ).strip()
            if not title:
                continue
            pid = str(
                item.get("productId")
                or item.get("id", "")
                or f"ali_{uuid.uuid4().hex[:10]}",
            )
            raw_price = item.get(
                "prices", {},
            )
            price = 0.0
            if isinstance(raw_price, dict):
                try:
                    price = float(
                        raw_price.get(
                            "salePrice", {},
                        ).get("minPrice", 0)
                        or 0,
                    )
                except (TypeError, ValueError):
                    price = 0.0
            image_url = str(
                item.get("image", {}).get("imgUrl", "")
                if isinstance(item.get("image"), dict)
                else item.get("imageUrl") or "",
            )
            product_url = (
                f"https://www.aliexpress.com/"
                f"item/{pid}.html"
            )
            out.append(
                ProductCandidate(
                    source="aliexpress_scraper",
                    external_id=pid,
                    title=title,
                    price=price,
                    cost=price * 0.4,
                    daily_sales=5.0,
                    saturation_score=0.6,
                    image_url=image_url,
                    url=product_url,
                    tags=(),
                    raw=dict(item),
                ),
            )
        return out

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enable,
                "query": self._query,
                "last_fetch_count": self._last_fetch_count,
                "last_error": self._last_error,
                "experimental": True,
            }
