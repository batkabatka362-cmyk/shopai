"""Shared external-signal hydrator — search/scraper-driven.

Companion to ``engines/_shopify_hydrator.py``. Where the
Shopify hydrator auto-fetches the store's own data, this
module hydrates EXTERNAL signals via the search + scraper
adapter families:

  * ``hydrate_competitors_via_search`` -- discovers competitor
    names + URLs via ``Capability.WEB_SEARCH`` (Serper / Brave
    / DDGS). DDGS is free + key-less, so this works
    out-of-the-box even on cold-install stores.

The motivating use case: ``engines/competition_analyzer`` used
to require the caller to pre-supply a competitor list, which
meant any cycle running without a hand-curated list failed
with "Competitors list is required". With this hydrator the
analyzer can auto-discover competitors from the niche or
explicit query, turning a hard-fail into a soft-degrade
(empty list -> hydrate -> at least basic positioning data
from the search snippets).

Behaviour (mirrors ``_shopify_hydrator.hydrate()``):

  * Non-empty ``supplied`` -> returned unchanged. No router call.
  * Empty/None ``supplied`` -> router lookup. If router or the
    WEB_SEARCH capability is unavailable, returns an empty
    list (so the caller can decide to fail vs degrade).
  * Adapter raises or returns ``ok=False`` -> empty list.
  * Search hits are normalised to the competitor dict shape
    the competition_analyzer expects:
    ``{id, name, url, snippet, source_query, prices,
       product_count}``. ``prices`` and ``product_count`` are
    populated as empty / zero so the downstream price
    comparator + positioning analyzer can run gracefully
    (they handle these defaults already).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from utils.logger import get_logger

logger = get_logger("engines.external_signal_hydrator")


_DEFAULT_MAX_RESULTS = 10
_MAX_LIMIT = 20


def hydrate_competitors_via_search(
    *,
    supplied: list[dict[str, Any]] | None,
    query: str | None = None,
    niche: str | None = None,
    max_results: int = _DEFAULT_MAX_RESULTS,
) -> list[dict[str, Any]]:
    """Pass-through if supplied; else discover competitors via WEB_SEARCH.

    Args:
        supplied: Caller-supplied competitor list. If non-empty,
            returned unchanged.
        query: Optional explicit search query (e.g.
            ``"LED facial device competitors"``). Used directly
            when present.
        niche: Optional niche keyword (e.g. ``"skincare"``).
            Combined into a generic competitor-discovery query
            when ``query`` isn't given.
        max_results: Max competitors to hydrate. Clamped to
            ``[1, 20]``. Default 10.

    Returns:
        List of competitor dicts. Empty when nothing supplied
        + nothing searchable. Never raises.
    """
    if supplied and isinstance(supplied, list):
        return [c for c in supplied if isinstance(c, dict)]

    effective_query = _build_query(query=query, niche=niche)
    if not effective_query:
        # Nothing to search for; let the caller decide whether
        # to fail or run degraded.
        return []

    limit = max(1, min(int(max_results or _DEFAULT_MAX_RESULTS), _MAX_LIMIT))

    hits = _run_web_search(query=effective_query, max_results=limit)
    if not hits:
        return []

    competitors: list[dict[str, Any]] = []
    seen_domains: set[str] = set()
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        url = str(hit.get("url") or "").strip()
        if not url:
            continue
        domain = _domain_from_url(url)
        if not domain:
            continue
        # Dedup by registered domain so amazon.com/listing1 and
        # amazon.com/listing2 don't both count as separate
        # competitors.
        if domain in seen_domains:
            continue
        seen_domains.add(domain)

        name = str(hit.get("title") or domain).strip()
        snippet = str(hit.get("snippet") or "").strip()
        source = str(hit.get("source") or "").strip()

        competitors.append({
            "id": domain,
            "name": name[:200],
            "url": url,
            "domain": domain,
            "snippet": snippet[:500],
            "source_query": effective_query,
            "discovered_via": source or "web_search",
            # Downstream price_comparator + positioning_analyzer
            # expect these keys; populate with safe defaults
            # rather than letting their .get() default chain
            # silently swallow the discovered competitor.
            "prices": {},
            "product_count": 0,
        })

    return competitors


def _build_query(
    *, query: str | None, niche: str | None,
) -> str:
    """Resolve the effective search query."""
    q = (query or "").strip()
    if q:
        return q
    n = (niche or "").strip()
    if n:
        return f"{n} brand competitors online store"
    return ""


def _run_web_search(
    *, query: str, max_results: int,
) -> list[dict[str, Any]]:
    """Call ``Capability.WEB_SEARCH`` via the router.

    Returns the list of hits ([] on any failure). Never raises.
    """
    try:
        from core.adapters import get_router
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "external_signal_hydrator: router import failed: %s", exc,
        )
        return []

    try:
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "external_signal_hydrator: router init failed: %s", exc,
        )
        return []

    try:
        result = router.execute(Capability.WEB_SEARCH, {
            "query": query,
            "max_results": max_results,
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "external_signal_hydrator: WEB_SEARCH raised for %r: %s",
            query, exc,
        )
        return []

    if not getattr(result, "ok", False):
        logger.debug(
            "external_signal_hydrator: WEB_SEARCH not-ok for %r: %s",
            query, getattr(result, "error", "unknown"),
        )
        return []

    data = result.data or {}
    if not isinstance(data, dict):
        return []
    # Search adapters return ``{results: [...], ...}`` or just
    # a list -- tolerate both.
    raw = data.get("results") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        # Some adapters put the list directly under ``data``;
        # the smart router preserves that shape.
        raw = data.get("hits") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    return raw


# Subdomain stripping: pull the registered domain so e.g.
# ``shop.example.com`` and ``www.example.com`` dedupe to
# ``example.com``. Public-suffix-list-accurate handling is
# overkill for competitor dedup; this regex catches the
# common cases (.com/.net/.io/.co.uk/...).
_DOMAIN_RE = re.compile(r"^(?:www\.|shop\.|store\.|m\.)?")


def _domain_from_url(url: str) -> str:
    """Extract a deduplicatable domain from a URL."""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except Exception:  # noqa: BLE001
        return ""
    host = (parsed.hostname or "").lower().strip()
    if not host:
        return ""
    return _DOMAIN_RE.sub("", host, count=1)
