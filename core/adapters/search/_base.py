"""SearchBaseAdapter — shared HTTP base for every web search adapter.

Concrete adapters (DDGS, Brave, Serper, …) inherit this class
and override only the vendor-specific bits:

  * ``base_url``       — vendor API endpoint
  * ``config_alias``   — key in ``ENV_ALIASES`` (empty string for
                          adapters that don't need a key)
  * ``_build_request`` — turn a query into vendor URL + headers
  * ``_parse_response``— turn the raw response into a list of
                          ``SearchHit`` dicts

The base handles:

  * HTTP execution + timeout + error mapping
  * Empty / malformed response normalisation
  * Result deduplication by URL
  * Result trimming to ``max_results``
  * AdapterResult assembly with latency / cost metadata

Result schema (``SearchHit``) is intentionally identical to the
``RawSearchResult`` TypedDict that ``engines/auto_research/types.py``
already defines, so the migration of ``search_executor.py`` is a
1:1 swap with no downstream renaming.
"""
from __future__ import annotations

from typing import Any, TypedDict

from utils.logger import get_logger

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
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

# Optional requests import — same pattern as
# ``data_pipeline/ingestion/api/shopify_api`` so the test suite
# can run in environments where requests isn't installed.
try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = get_logger("adapters.search")


class SearchHit(TypedDict):
    """One normalised search result.

    Identical shape to ``engines.auto_research.types.RawSearchResult``
    so consumers don't have to translate fields when migrating
    from the old simulated search to the real adapter layer.
    """

    title: str
    url: str
    snippet: str
    source: str
    retrieved_at: str


_DEFAULT_TIMEOUT = 15.0
_DEFAULT_MAX_RESULTS = 10


class SearchBaseAdapter(BaseAdapter):
    """Abstract base for every web-search adapter.

    Concrete adapters MUST set:

      * ``name``           — registry key
      * ``base_url``       — vendor endpoint
      * ``capabilities``   — set of ``Capability`` enums

    They MAY set:

      * ``config_alias``   — env var alias for the API key
                              (empty string when no key is needed)
      * ``priority``       — router preference (0-100)
      * ``cost_per_call``  — average $/call (0 for free vendors)
      * ``free_tier_*``    — quota hints for the metrics layer

    Concrete adapters MUST override ``_build_request`` and
    ``_parse_response``. The base provides ``_execute`` which
    glues them together with HTTP + dedup + AdapterResult
    assembly.
    """

    category = AdapterCategory.SEARCH
    capabilities = {Capability.WEB_SEARCH}

    base_url: str = ""
    config_alias: str = ""    # empty = no key needed (DDGS)
    timeout: float = _DEFAULT_TIMEOUT
    max_results_default: int = _DEFAULT_MAX_RESULTS

    free_tier_daily_limit: int = 0
    free_tier_monthly_limit: int = 0

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url:
            return False
        # config_alias = "" means "no key needed" — adapter is
        # always configured (DDGS, instant answers, etc.)
        if not self.config_alias:
            return True
        return bool(get_config().get(self.config_alias))

    def _api_key(self) -> str:
        """Return the API key for this adapter, raising if
        unset. Should not be called by adapters that don't
        require a key (their ``is_configured`` returns True
        regardless)."""
        if not self.config_alias:
            return ""
        key = get_config().get(self.config_alias)
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
        if capability != Capability.WEB_SEARCH:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        query = params.get("query") or params.get("q")
        if not isinstance(query, str) or not query.strip():
            raise AdapterValidationError(
                self.name, "'query' must be a non-empty string",
            )

        max_results = int(params.get("max_results") or self.max_results_default)
        max_results = max(1, min(max_results, 50))

        url, headers = self._build_request(query, max_results)
        raw = self._http_get(url, headers=headers)
        hits = self._parse_response(raw, query=query)
        hits = self._dedup_and_trim(hits, max_results)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "query": query,
                "hits": hits,
                "count": len(hits),
            },
            raw=raw,
        )

    # ── Vendor-specific hooks ──────────────────────────────────

    def _build_request(
        self,
        query: str,
        max_results: int,
    ) -> tuple[str, dict[str, str]]:
        """Return ``(url, headers)`` for the given query.

        Concrete adapters override this to translate the query
        into their vendor's URL + auth headers.
        """
        raise NotImplementedError(
            f"{type(self).__name__}._build_request must be implemented",
        )

    def _parse_response(
        self,
        raw: Any,
        *,
        query: str,
    ) -> list[SearchHit]:
        """Parse the vendor's raw response into a list of
        ``SearchHit`` dicts.

        Concrete adapters override this with their schema-
        specific parser. Returning an empty list is fine — the
        AdapterResult is still ``ok`` (the query just produced
        no hits).
        """
        raise NotImplementedError(
            f"{type(self).__name__}._parse_response must be implemented",
        )

    # ── HTTP helper ────────────────────────────────────────────

    def _http_get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """GET *url* with W962-65 shared retry helper. Returns
        parsed JSON when possible; falls back to raw text for
        HTML scrapers."""
        from core.adapters._http_retry import http_retry
        response = http_retry(
            lambda: _requests.get(
                url, headers=headers or {},
                timeout=self.timeout,
            ),
            adapter_name=self.name,
            timeout=self.timeout,
            parse_json=False,
        )
        try:
            return response.json()
        except ValueError:
            return response.text

    def _raise_for_status(self, status: int, body: str) -> None:
        snippet = (body or "")[:200]
        if status in (401, 403):
            raise AdapterAuthError(
                self.name,
                f"vendor rejected credentials ({status}): {snippet}",
            )
        if status == 429:
            raise AdapterRateLimited(
                self.name, f"rate limit ({status}): {snippet}",
            )
        if 500 <= status < 600:
            raise AdapterUnavailable(
                self.name, f"vendor 5xx ({status}): {snippet}",
            )
        raise AdapterError(
            self.name, f"vendor returned {status}: {snippet}",
        )

    # ── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _dedup_and_trim(
        hits: list[SearchHit],
        max_results: int,
    ) -> list[SearchHit]:
        """Drop duplicate URLs (case-insensitive) and trim to
        the caller's ``max_results`` limit. Order is preserved
        — first occurrence of each URL wins."""
        seen: set[str] = set()
        out: list[SearchHit] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            url = str(hit.get("url", "") or "").strip().lower()
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(hit)
            if len(out) >= max_results:
                break
        return out

    @staticmethod
    def _now_iso() -> str:
        """Return the current UTC time as an ISO-8601 string,
        used in every ``SearchHit.retrieved_at`` field."""
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
