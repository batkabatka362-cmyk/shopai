"""Peer store observer — scrape public Shopify ``/products.json``.

Every Shopify store by default exposes ``/products.json`` (up to
250 products per page) on its public domain. No auth, no scraping
tricks. The observer fetches this for a list of peer stores and
converts each product into a ``ProductCandidate`` so ShopAI can
learn what's trending across the dropshipping ecosystem without
touching private data.

Usage:

    obs = PeerStoreObserverSource(
        stores=[
            "mystore.myshopify.com",
            "pet-trend.com",
        ],
        per_store_limit=50,
    )
    candidates = obs.fetch()

Rate-limit: 1 req/store with ``timeout`` seconds; respects HTTP
429 / 503 via exponential retry (re-uses the same backoff contract
as AdsBaseAdapter — see ``backoff_base_s``). If a store's feed is
blocked / 404s / parse-errors, that store is skipped and the rest
of the feeds keep going.

Demand + saturation proxies:
  * ``daily_sales`` ≈ updated_at freshness × published rank proxy
    — a hack until we wire proper peer-level sales estimators
  * ``saturation_score`` ≈ 0.5 by default; the brain's
    ``concept_former`` will refine this from co-occurrence across
    peer stores over time.

Pure stdlib + requests.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from agents.research.winner_searcher import (
    ProductCandidate, WinnerSource,
)
from utils.logger import get_logger


logger = get_logger("agents.research.sources.peer_store_observer")


_DEFAULT_TIMEOUT = 15.0
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_BACKOFF_S = 0.5
_PRODUCTS_PATH = "/products.json"


@dataclass
class _FetchStat:
    store: str
    products_seen: int = 0
    last_fetched_ts: float = 0.0
    last_error: str = ""


class PeerStoreObserverSource(WinnerSource):
    """Shopify ``/products.json`` observer across N peer stores."""

    name = "peer_store_observer"

    def __init__(
        self,
        stores: Iterable[str],
        *,
        per_store_limit: int = 50,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        backoff_base_s: float = _DEFAULT_BACKOFF_S,
        http: Any = None,
    ) -> None:
        self._stores = [
            s.strip() for s in stores if s and s.strip()
        ]
        if per_store_limit < 1:
            raise ValueError(
                "per_store_limit must be ≥ 1",
            )
        if timeout <= 0:
            raise ValueError("timeout must be > 0")
        if max_retries < 0:
            raise ValueError("max_retries must be ≥ 0")
        self._per_store = int(per_store_limit)
        self._timeout = float(timeout)
        self._max_retries = int(max_retries)
        self._backoff_base = float(backoff_base_s)
        self._http = http
        self._lock = threading.Lock()
        self._stats: dict[str, _FetchStat] = {
            s: _FetchStat(store=s) for s in self._stores
        }

    def is_available(self) -> bool:
        return len(self._stores) > 0

    def fetch(
        self, *, limit: int = 100,
    ) -> list[ProductCandidate]:
        out: list[ProductCandidate] = []
        remaining = int(limit)
        for store in self._stores:
            if remaining <= 0:
                break
            take = min(remaining, self._per_store)
            try:
                products = self._fetch_store(store, take)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "peer store %s fetch failed: %s",
                    store, exc,
                )
                with self._lock:
                    self._stats[store].last_error = str(exc)
                continue
            out.extend(products)
            remaining -= len(products)
        return out

    def _fetch_store(
        self, store: str, limit: int,
    ) -> list[ProductCandidate]:
        url = self._store_url(store, limit)
        raw = self._get_with_retry(url)
        with self._lock:
            stat = self._stats.setdefault(
                store, _FetchStat(store=store),
            )
            stat.last_fetched_ts = time.time()
        products = []
        entries = []
        if isinstance(raw, dict):
            entries = raw.get("products") or []
        if not isinstance(entries, list):
            entries = []
        for p in entries[: max(1, int(limit))]:
            candidate = self._to_candidate(store, p)
            if candidate is not None:
                products.append(candidate)
        with self._lock:
            stat.products_seen += len(products)
        return products

    def _store_url(self, store: str, limit: int) -> str:
        base = store.strip()
        if not base.startswith("http"):
            base = f"https://{base}"
        base = base.rstrip("/")
        return f"{base}{_PRODUCTS_PATH}?limit={limit}"

    def _get_with_retry(self, url: str) -> Any:
        """Lightweight retry loop for peer-level HTTP. Distinct
        from AdsBaseAdapter's retry because that one is class-
        wrapped; keeping this local keeps the source free-standing.
        """
        import requests
        client = self._http or requests
        max_attempts = max(1, self._max_retries + 1)
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                resp = client.get(
                    url, timeout=self._timeout,
                    headers={
                        "User-Agent": (
                            "ShopAI/1.0 (peer-observer; "
                            "public /products.json only)"
                        ),
                        "Accept": "application/json",
                    },
                )
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except Exception as exc:  # noqa: BLE001
                        raise RuntimeError(
                            f"non-JSON response: {exc}",
                        ) from exc
                if resp.status_code in (429, 503):
                    last_exc = RuntimeError(
                        f"peer {resp.status_code}",
                    )
                    if attempt + 1 >= max_attempts:
                        raise last_exc
                    time.sleep(
                        self._backoff_base * (2 ** attempt),
                    )
                    continue
                if 500 <= resp.status_code < 600:
                    last_exc = RuntimeError(
                        f"peer 5xx: {resp.status_code}",
                    )
                    if attempt + 1 >= max_attempts:
                        raise last_exc
                    time.sleep(
                        self._backoff_base * (2 ** attempt),
                    )
                    continue
                raise RuntimeError(
                    f"peer HTTP {resp.status_code}",
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt + 1 >= max_attempts:
                    raise
                time.sleep(
                    self._backoff_base * (2 ** attempt),
                )
        assert last_exc is not None  # noqa: S101
        raise last_exc

    def _to_candidate(
        self, store: str, product: dict[str, Any],
    ) -> ProductCandidate | None:
        if not isinstance(product, dict):
            return None
        title = str(product.get("title") or "").strip()
        if not title:
            return None
        variants = product.get("variants") or []
        price = 0.0
        if isinstance(variants, list) and variants:
            first = variants[0]
            if isinstance(first, dict):
                try:
                    price = float(first.get("price", 0.0))
                except (TypeError, ValueError):
                    price = 0.0
        images = product.get("images") or []
        image_url = ""
        if isinstance(images, list) and images:
            first_img = images[0]
            if isinstance(first_img, dict):
                image_url = str(first_img.get("src", ""))
        handle = str(product.get("handle") or "").strip()
        base = store
        if not base.startswith("http"):
            base = f"https://{base}"
        product_url = (
            f"{base.rstrip('/')}/products/{handle}"
            if handle else base
        )
        ext_id = str(product.get("id") or "")
        if not ext_id:
            # derive from store + handle so dedupe is stable
            digest = hashlib.sha1(
                f"{store}|{handle or title}".encode("utf-8"),
            ).hexdigest()[:16]
            ext_id = f"peer_{digest}"
        daily_sales = _freshness_proxy(
            product.get("updated_at"),
            product.get("published_at"),
        )
        tags_raw = product.get("tags") or ""
        if isinstance(tags_raw, str):
            tags = tuple(
                t.strip() for t in tags_raw.split(",")
                if t.strip()
            )
        elif isinstance(tags_raw, list):
            tags = tuple(
                str(t).strip() for t in tags_raw if t
            )
        else:
            tags = ()
        return ProductCandidate(
            source=f"peer:{store}",
            external_id=ext_id,
            title=title,
            price=price,
            cost=0.0,
            daily_sales=daily_sales,
            saturation_score=0.5,
            image_url=image_url,
            url=product_url,
            tags=tags,
            raw={"store": store, "product": product},
        )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stores": list(self._stores),
                "per_store_limit": self._per_store,
                "by_store": {
                    s: {
                        "products_seen": stat.products_seen,
                        "last_fetched_ts": (
                            stat.last_fetched_ts
                        ),
                        "last_error": stat.last_error,
                    }
                    for s, stat in self._stats.items()
                },
            }


def _freshness_proxy(
    updated_at: Any,
    published_at: Any,
) -> float:
    """Return a rough demand proxy in the [0, 50] daily-sales
    range — products updated within the last week ≈ hot, older
    products ≈ stale. This is a placeholder until real sales
    estimators (via CJ / peer checkout probes) are wired.
    """
    ts_candidate = updated_at or published_at
    if not ts_candidate:
        return 5.0
    try:
        if isinstance(ts_candidate, (int, float)):
            dt = _dt.datetime.fromtimestamp(
                float(ts_candidate), tz=_dt.timezone.utc,
            )
        else:
            dt = _dt.datetime.fromisoformat(
                str(ts_candidate).replace("Z", "+00:00"),
            )
    except Exception:  # noqa: BLE001
        return 5.0
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    days_old = max(0.0, (now - dt).total_seconds() / 86_400.0)
    if days_old <= 1:
        return 40.0
    if days_old <= 7:
        return 20.0
    if days_old <= 30:
        return 8.0
    return 2.0
