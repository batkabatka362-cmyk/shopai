"""Search Executor — runs search queries through the adapter layer.

Responsibility: take a list of ``SearchQuery`` dicts, dispatch
them to the SmartRouter via ``Capability.WEB_SEARCH``, and
return unified ``RawSearchResult`` lists.

History:

  * **Pre-cleanup**: shipped an 8-entry hardcoded
    ``_SIMULATED_CORPUS`` of fake article titles with
    example.com URLs, scored by token-overlap heuristic. Every
    research query returned the same 5 fake "sources".
  * **Cleanup pass**: ripped the corpus out and made
    ``execute_searches`` return ``[]`` so the engine flow's
    "no results" branch fires cleanly.
  * **This migration**: routes each query through the adapter
    SmartRouter using ``Capability.WEB_SEARCH``. The router
    picks the best registered search adapter (Brave → Serper
    → DDGS) per call. Out-of-the-box ShopAI gets the DDGS
    adapter for free (no API key); operators who want higher
    quality wire up Brave or Serper via env vars.

When the router has no configured search adapter the function
still returns ``[]`` — the cleanup invariant ("no fake data,
ever") is preserved.

Model note: no model usage — pure I/O layer.
"""
from __future__ import annotations

import copy
from typing import Any

from utils.logger import get_logger

from .types import RawSearchResult, SearchQuery

logger = get_logger("auto_research.search")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_searches(
    queries: list[SearchQuery],
    *,
    max_results_per_query: int = 5,
) -> list[RawSearchResult]:
    """Execute a batch of search queries via the adapter layer.

    Never mutates *queries* — works on a deep copy. Results are
    deduplicated by URL across the whole batch.

    Returns an empty list when:

      * ``queries`` is empty
      * the adapter package is unavailable (import failure)
      * the SmartRouter has no configured WEB_SEARCH adapter
      * every router call fails (vendor outages, rate limits)

    The empty-list path mirrors the cleanup behaviour so the
    flow's "no results" branch fires cleanly.
    """
    safe_queries: list[SearchQuery] = copy.deepcopy(queries)
    if not safe_queries:
        return []

    router = _get_router()
    if router is None:
        return []

    all_results: list[RawSearchResult] = []
    seen_urls: set[str] = set()

    for query in safe_queries:
        query_text = query.get("text", "") if isinstance(query, dict) else ""
        if not query_text:
            continue

        hits = _route_one(router, query_text, max_results_per_query)
        for hit in hits:
            url = str(hit.get("url", "") or "").strip().lower()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            all_results.append(RawSearchResult(
                title=str(hit.get("title", "") or ""),
                url=str(hit.get("url", "") or ""),
                snippet=str(hit.get("snippet", "") or ""),
                source=str(hit.get("source", "") or ""),
                retrieved_at=str(hit.get("retrieved_at", "") or ""),
            ))

    return all_results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_router() -> Any | None:
    """Return the adapter SmartRouter singleton, or ``None`` if
    the adapter package is unavailable / import fails. Logs at
    DEBUG level so a missing adapter layer doesn't spam the
    operator's console."""
    try:
        from core.adapters import get_router
    except Exception as exc:  # noqa: BLE001
        logger.debug("adapter import failed: %s", exc)
        return None
    return get_router()


def _route_one(
    router: Any,
    query_text: str,
    max_results: int,
) -> list[dict[str, Any]]:
    """Route a single query through the SmartRouter and return
    its hit list (possibly empty).

    Failures (no configured adapter, every candidate down,
    rate limit) are swallowed — the caller treats them as
    "this query produced no hits" rather than propagating the
    exception. The metrics layer already records the failure
    cause via ``MetricsCollector``.
    """
    try:
        from core.adapters import Capability
    except Exception:  # noqa: BLE001
        return []

    try:
        result = router.execute(
            Capability.WEB_SEARCH,
            {"query": query_text, "max_results": max_results},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("search router raised for %r: %s", query_text, exc)
        return []

    if not result.ok:
        return []
    data = result.data or {}
    hits = data.get("hits") or []
    return hits if isinstance(hits, list) else []
