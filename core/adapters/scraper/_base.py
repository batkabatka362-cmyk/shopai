"""ScraperBaseAdapter — shared HTTP base for web scrapers.

Concrete adapters (Firecrawl today; Jina Reader, Apify, Bright
Data later) inherit this class and override only the
vendor-specific bits:

  * ``base_url``                 — vendor API root
  * ``config_alias``             — ``ENV_ALIASES`` key for the
                                    API credential
  * ``_scrape_url``              — endpoint that scrapes a page
  * ``_auth_headers``            — vendor-specific auth header
  * ``_build_scrape_payload``    — normalised params → vendor
                                    body
  * ``_parse_scrape_response``   — vendor response → normalised
                                    result dict

The base handles:

  * Capability dispatch for ``Capability.SCRAPE_PAGE``
  * Required-field validation (``url``; optional ``formats`` /
    ``only_main_content`` / ``include_tags`` / ``exclude_tags``)
  * URL shape validation (must be http/https)
  * HTTP POST execution with typed error mapping
  * AdapterResult assembly

Normalised request shape (vendor-agnostic):

    {
        "url":               "https://competitor.example.com/products/1",  # required
        "formats":           ["markdown", "html"],   # optional
        "only_main_content": True,                    # optional
        "include_tags":      ["article", "main"],    # optional
        "exclude_tags":      ["nav", "footer"],      # optional
        "wait_for":          2_000,                    # optional ms
    }

Normalised response shape:

    {
        "url":       "https://...",
        "title":     "Product name — Competitor Store",
        "markdown":  "# Product name\\n\\n...",
        "html":      "<article>...</article>",
        "text":      "plain text extraction",
        "status":    200,
        "metadata":  {"description": "...", "og:image": "..."},
    }

Scope note: Wave 1 covers *single-page scrape* only. Crawling
(following links), PDF extraction, screenshot capture, and
structured-data extraction are out of scope — they belong in a
later wave once the one-page path is proven.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from .._per_store_credentials import (
    resolve_per_store as _resolve_per_store,
)
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = get_logger("adapters.scraper")


# Scraping is slow — a competitor page may take 10s+ to render,
# and Firecrawl's sync endpoint can block even longer when the
# target is JavaScript-heavy. Generous default so happy-path
# scrapes never spuriously time out.
_DEFAULT_TIMEOUT = 60.0


class ScraperBaseAdapter(BaseAdapter):
    """Abstract base for every scraper adapter.

    Concrete adapters MUST set:

      * ``name``         — registry key (e.g. ``"firecrawl"``)
      * ``base_url``     — vendor API root
      * ``config_alias`` — env alias for the API key

    They MAY override:

      * ``priority``      — router preference (0-100)
      * ``cost_per_call`` — average $/page (Firecrawl pay-as-you-
                            go is roughly $0.002/page)
      * ``timeout``       — per-request timeout in seconds
    """

    category = AdapterCategory.SCRAPER
    capabilities = {Capability.SCRAPE_PAGE}

    base_url: str = ""
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    cost_per_call: float = 0.0
    priority: int = 50

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url or not self.config_alias:
            return False
        return bool((_resolve_per_store(self.config_alias) or get_config().get(self.config_alias)))

    def _api_key(self) -> str:
        key = (_resolve_per_store(self.config_alias) or get_config().get(self.config_alias))
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env or self.config_alias})",
            )
        return key

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability != Capability.SCRAPE_PAGE:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        self._validate_scrape(params)
        url = self._scrape_url()
        body = self._build_scrape_payload(params)
        raw = self._http_post(url, body, headers=self._auth_headers())
        normalised = self._parse_scrape_response(raw, params)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data=normalised,
            cost_usd=float(self.cost_per_call),
            raw=raw,
        )

    # ── Validation ─────────────────────────────────────────────

    def _validate_scrape(self, params: dict[str, Any]) -> None:
        url = params.get("url")
        if not url or not isinstance(url, str):
            raise AdapterValidationError(
                self.name, "'url' is required for scrape_page",
            )
        if not (url.startswith("http://") or url.startswith("https://")):
            raise AdapterValidationError(
                self.name,
                f"'url' must be http(s) scheme, got {url!r}",
            )

        formats = params.get("formats")
        if formats is not None and not isinstance(formats, (list, tuple)):
            raise AdapterValidationError(
                self.name,
                f"'formats' must be a list, got {type(formats).__name__}",
            )

        wait_for = params.get("wait_for")
        if wait_for is not None:
            try:
                w = int(wait_for)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"'wait_for' must be an int (got {wait_for!r})",
                ) from exc
            if w < 0 or w > 30_000:
                raise AdapterValidationError(
                    self.name,
                    f"'wait_for' must be 0-30000 ms (got {w})",
                )

    # ── Vendor-specific hooks (override in subclasses) ────────

    def _scrape_url(self) -> str:
        raise NotImplementedError(
            f"{type(self).__name__}._scrape_url must be implemented",
        )

    def _auth_headers(self) -> dict[str, str]:
        """Default: Bearer token. Override when the vendor uses
        a different scheme."""
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_scrape_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._build_scrape_payload must be implemented",
        )

    def _parse_scrape_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._parse_scrape_response must be implemented",
        )

    # ── HTTP ───────────────────────────────────────────────────

    def _http_post(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        """W962-65: shared retry helper."""
        from core.adapters._http_retry import http_retry
        return http_retry(
            lambda: _requests.post(
                url, json=body, headers=headers,
                timeout=self.timeout,
            ),
            adapter_name=self.name,
            timeout=self.timeout,
        )
