"""Meta Ad Library source — free ad-spy winner signal.

Sprint 3 S3-6 (P2, L2 in docs/AGI_STACK.md). Meta publishes every
active ad worldwide through the Ad Library (archive) at
``graph.facebook.com/ads_archive``. Reach of a product's ad
campaign is a strong proxy for winner-ness: if competitors are
running the same ad for weeks, it's working.

This source is *experimental* — the public endpoint requires a
Facebook developer token and returns ad creatives (not products),
so the mapping into ``ProductCandidate`` is necessarily lossy.
Activation: set ``META_AD_LIBRARY_TOKEN`` in env AND
``SHOPAI_ENABLE_META_ADS_LIBRARY=1``.

Fragility: Meta's API occasionally rotates field names, paginates
inconsistently, or throttles. On any parse/HTTP failure the
source degrades to ``[]`` with ``stats().last_error`` populated —
never blocks the autopilot.

Output candidates get:
  * ``source = meta_ads_library``
  * ``title`` from ad creative body (truncated)
  * ``url`` = ad_snapshot_url when present
  * ``cost``/``price`` synthesized at a 2.5× margin when the ad
    mentions a price tag; otherwise left at 0 so downstream
    scoring can ignore it until the owner enriches the row.

Pure stdlib + requests. Deterministic under a fixed http client.
"""
from __future__ import annotations

import os
import re
import threading
from typing import Any

from agents.research.winner_searcher import (
    ProductCandidate,
    WinnerSource,
)
from utils.logger import get_logger


logger = get_logger(
    "agents.research.sources.meta_ads_library",
)


_ENV_TOKEN = "META_AD_LIBRARY_TOKEN"
_ENV_ENABLE = "SHOPAI_ENABLE_META_ADS_LIBRARY"
_DEFAULT_ENDPOINT = (
    "https://graph.facebook.com/v19.0/ads_archive"
)
_DEFAULT_TIMEOUT = 20.0
_PRICE_RE = re.compile(
    r"\$(\d+(?:\.\d{1,2})?)",
)


class MetaAdsLibrarySource(WinnerSource):
    """Meta Ad Library archive reader — experimental."""

    name = "meta_ads_library"
    experimental = True

    def __init__(
        self,
        *,
        token: str = "",
        ad_reached_countries: tuple[str, ...] = ("US", "GB"),
        search_terms: str = "",
        per_fetch_limit: int = 25,
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout: float = _DEFAULT_TIMEOUT,
        http: Any = None,
        enable_override: bool | None = None,
        cost_margin_ratio: float = 2.5,
    ) -> None:
        self._token = (
            token if token else os.environ.get(_ENV_TOKEN, "")
        )
        self._countries = tuple(
            c for c in ad_reached_countries if c
        )
        self._terms = str(search_terms)
        self._limit = int(per_fetch_limit)
        self._endpoint = str(endpoint).rstrip("/")
        self._timeout = float(timeout)
        self._http = http
        self._margin_ratio = float(cost_margin_ratio)
        self._enable = (
            bool(enable_override)
            if enable_override is not None
            else os.environ.get(_ENV_ENABLE, "") == "1"
        )
        self._lock = threading.Lock()
        self._last_fetch_count = 0
        self._last_error = ""

    def is_available(self) -> bool:
        return bool(self._enable) and bool(self._token)

    # ── Fetch ────────────────────────────────────────────

    def fetch(
        self, *, limit: int = 100,
    ) -> list[ProductCandidate]:
        if not self.is_available():
            with self._lock:
                self._last_error = (
                    "source disabled — require "
                    f"{_ENV_ENABLE}=1 and {_ENV_TOKEN}"
                )
            return []
        take = min(int(limit), self._limit)
        try:
            raw = self._fetch_json(take)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"fetch failed: {exc}"
            logger.debug(
                "meta ad library fetch failed: %s", exc,
            )
            return []
        candidates = self._normalise(raw, limit=take)
        with self._lock:
            self._last_fetch_count = len(candidates)
            if candidates:
                self._last_error = ""
            elif not self._last_error:
                self._last_error = (
                    "no candidates parsed — Meta may have "
                    "changed field shape"
                )
        return candidates

    def _client(self) -> Any:
        if self._http is not None:
            return self._http
        import requests
        return requests

    def _fetch_json(self, take: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "access_token": self._token,
            "search_terms": self._terms or "product",
            "ad_reached_countries": ",".join(
                self._countries,
            ),
            "ad_type": "ALL",
            "fields": (
                "ad_snapshot_url,"
                "ad_creative_bodies,"
                "page_name,"
                "ad_creative_link_titles,"
                "ad_creative_link_descriptions,"
                "impressions"
            ),
            "limit": take,
        }
        resp = self._client().get(
            self._endpoint,
            params=params,
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            body = (resp.text or "")[:200]
            raise RuntimeError(
                f"HTTP {resp.status_code}: {body}"
            )
        try:
            return resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"bad JSON: {exc}",
            ) from exc

    def _normalise(
        self,
        raw: dict[str, Any],
        *,
        limit: int,
    ) -> list[ProductCandidate]:
        items = raw.get("data") or []
        if not isinstance(items, list):
            return []
        out: list[ProductCandidate] = []
        for item in items[: limit]:
            if not isinstance(item, dict):
                continue
            bodies = item.get("ad_creative_bodies") or []
            link_titles = (
                item.get("ad_creative_link_titles") or []
            )
            title = ""
            if link_titles and isinstance(
                link_titles[0], str,
            ):
                title = link_titles[0]
            elif bodies and isinstance(bodies[0], str):
                title = bodies[0].split("\n", 1)[0][:120]
            if not title:
                continue
            price = self._extract_price(
                bodies[0] if bodies else "",
            )
            pid = str(
                item.get("id")
                or item.get("ad_snapshot_url")
                or title[:40],
            )
            url = str(item.get("ad_snapshot_url") or "")
            cost = (
                round(price / self._margin_ratio, 2)
                if price > 0 else 0.0
            )
            out.append(ProductCandidate(
                source=self.name,
                external_id=pid,
                title=str(title)[:180],
                price=price,
                cost=cost,
                daily_sales=0.0,
                saturation_score=0.7,
                image_url="",
                url=url,
                tags=(),
                raw=dict(item),
            ))
        return out

    def _extract_price(self, text: str) -> float:
        if not text:
            return 0.0
        match = _PRICE_RE.search(text)
        if not match:
            return 0.0
        try:
            return float(match.group(1))
        except ValueError:
            return 0.0

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enable,
                "has_token": bool(self._token),
                "countries": list(self._countries),
                "search_terms": self._terms,
                "last_fetch_count": self._last_fetch_count,
                "last_error": self._last_error,
                "experimental": True,
            }
