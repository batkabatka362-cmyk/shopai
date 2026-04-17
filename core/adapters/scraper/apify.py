"""ApifyAdapter — Apify actor-based web scraper.

Second adapter for ``Capability.SCRAPE_PAGE``. Firecrawl was the
first — Apify is added so the router can fall back when
Firecrawl is rate-limited, blocked by a specific target, or has
exhausted its monthly quota.

Why Apify:

  * **Actor marketplace**   — Apify exposes 2000+ pre-built
    scrapers ("actors"). This adapter defaults to the official
    ``apify/website-content-crawler`` which handles JavaScript,
    bot-detection, and content extraction in one call — roughly
    the same feature set as Firecrawl's ``/scrape``.
  * **Residential proxies** — included in the actor run, so
    sites that block Firecrawl often work on Apify.
  * **Pay-as-you-go**       — $0.25 per 1K pages on the free tier
    (first 5K pages/month are free).

Auth: Bearer token in ``Authorization`` header —
``APIFY_API_TOKEN``. Already wired into ``ENV_ALIASES`` below.

Endpoint used:

  * ``POST /v2/acts/{actor}/run-sync-get-dataset-items`` — runs
    the actor and blocks until the output dataset is written,
    returning the items directly. One call, one page, no
    webhook dance.

Actor routing: the default is ``apify/website-content-crawler``
but a caller can override via ``params["actor"]`` — e.g.
``"apify/web-scraper"`` for a more customisable Puppeteer
runtime, or a user's own private actor. The ``~`` separator in
the URL path is handled automatically (Apify accepts both ``/``
and ``~`` in the actor ID but the REST API canonicalises to
``~``).

Reference: https://docs.apify.com/api/v2#/reference/actor-runs/
           run-actor-synchronously-and-get-dataset-items
"""
from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ._base import ScraperBaseAdapter


# Default actor: Apify's flagship content crawler. Single-page
# friendly via maxCrawlPages=1, handles JS, returns text +
# markdown + html + metadata in one payload.
_DEFAULT_ACTOR = "apify/website-content-crawler"


class ApifyAdapter(ScraperBaseAdapter):
    """Apify actor-based web scraper (single-page mode)."""

    name = "apify"
    base_url = "https://api.apify.com"
    config_alias = "apify"

    # Lower than Firecrawl (80) so the router prefers Firecrawl
    # when both are configured — Apify is slightly pricier
    # per-page on paid plans. Operators who prefer Apify can
    # bump this via RouteContext.prefer or an adapter-weight
    # override.
    priority = 70
    # Conservative estimate: free tier is free, paid tier is
    # $0.25/1K pages = $0.00025/page. Round up slightly because
    # the website-content-crawler actor consumes compute units
    # beyond the per-page flat cost.
    cost_per_call = 0.0005

    # ── URL / auth ────────────────────────────────────────────

    def _scrape_url(self, params: dict[str, Any] | None = None) -> str:
        """Build the run-sync endpoint for the target actor.

        Apify accepts both ``username/actor-name`` and
        ``username~actor-name`` in the URL path; we canonicalise
        to ``~`` because that avoids any ambiguity with the REST
        path hierarchy (a slash in the actor ID collides with
        ``/run-sync-get-dataset-items``).
        """
        actor = (
            (params or {}).get("actor") or _DEFAULT_ACTOR
        )
        actor_path = str(actor).replace("/", "~")
        return (
            f"{self.base_url}/v2/acts/{actor_path}/"
            f"run-sync-get-dataset-items"
        )

    # ── Payload translation ──────────────────────────────────

    def _build_scrape_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Translate the normalised request into the
        ``apify/website-content-crawler`` input schema.

        Single-page mode: ``maxCrawlDepth=0`` and
        ``maxCrawlPages=1`` together guarantee the crawler stops
        at the start URL. ``crawlerType`` chooses the rendering
        engine — we use ``playwright:chrome`` which is the
        strongest option for React/Vue/SPA storefronts.

        The actor accepts dozens of other knobs (proxies,
        cookies, user-agent, etc.); we pass a minimal subset and
        let the actor use sensible defaults. Callers that need
        fine control can drop a full ``custom_input`` dict which
        overrides the entire body — useful for private actors
        with non-crawler schemas.
        """
        custom = params.get("custom_input")
        if isinstance(custom, dict) and custom:
            # Caller fully owns the input — we just pass through.
            return dict(custom)

        body: dict[str, Any] = {
            "startUrls": [{"url": params["url"]}],
            "maxCrawlDepth": 0,
            "maxCrawlPages": 1,
            "crawlerType": params.get("crawler_type") or "playwright:chrome",
            "saveMarkdown": True,
            "saveHtml": "html" in (params.get("formats") or []),
        }

        # Optional ``wait_for`` maps to the actor's pageLoadTimeoutSecs.
        wait_for = params.get("wait_for")
        if wait_for is not None:
            # wait_for is in ms (scraper base validated it); the
            # actor expects seconds. Round up so a 1500 ms hint
            # becomes a 2 s timeout — better to wait slightly
            # longer than to truncate.
            secs = max(1, int((int(wait_for) + 999) // 1000))
            body["pageLoadTimeoutSecs"] = secs

        exclude_tags = params.get("exclude_tags")
        if exclude_tags:
            body["removeElementsCssSelector"] = ", ".join(
                str(t) for t in exclude_tags
            )

        return body

    # ── Dispatch override for actor in URL ──────────────────

    # The scraper base's ``_execute`` calls ``_scrape_url()``
    # without params, but Apify's URL depends on the ``actor``
    # param. We override _execute to thread params through.
    def _execute(
        self,
        capability: Any,
        params: dict[str, Any],
    ) -> Any:
        from ..base import AdapterResult, Capability
        from ..errors import AdapterValidationError

        if capability != Capability.SCRAPE_PAGE:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        self._validate_scrape(params)
        url = self._scrape_url(params)
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

    # ── Response parsing ──────────────────────────────────────

    def _parse_scrape_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Apify's run-sync-get-dataset-items returns a JSON ARRAY
        of dataset items — one item per scraped page. For
        single-page mode we expect exactly one item::

            [
                {
                    "url":       "https://...",
                    "loadedUrl": "https://...",
                    "title":     "Page title",
                    "text":      "plain text",
                    "markdown":  "# Page title\\n\\n...",
                    "html":      "<article>...</article>",
                    "metadata":  {"description": "...", ...},
                    "crawl":     {"httpStatusCode": 200, ...}
                }
            ]

        An empty array is surfaced loudly: a successful run that
        produced no items usually means the target blocked the
        crawler or the URL 404'd — silently returning an empty
        payload would make the router record a phantom success.
        """
        if not isinstance(raw, list):
            raise AdapterError(
                self.name,
                f"expected JSON array, got {type(raw).__name__}",
            )
        if not raw:
            raise AdapterError(
                self.name,
                "apify returned an empty dataset — target likely "
                "blocked, 404'd, or timed out during render",
            )

        item = raw[0]
        if not isinstance(item, dict):
            raise AdapterError(
                self.name,
                f"dataset item not a dict: {type(item).__name__}",
            )

        metadata = item.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        crawl = item.get("crawl") or {}
        if not isinstance(crawl, dict):
            crawl = {}

        markdown = str(item.get("markdown", "") or "")
        html = str(item.get("html", "") or "")
        text = str(
            item.get("text", "") or item.get("content", "") or markdown,
        )

        # httpStatusCode is the most authoritative status —
        # fall back to 0 rather than inventing a 200 so
        # downstream consumers can distinguish "we don't know"
        # from "definitely succeeded".
        status = int(crawl.get("httpStatusCode", 0) or 0)

        return {
            "url": str(
                item.get("loadedUrl", "")
                or item.get("url", "")
                or params.get("url", ""),
            ),
            "title": str(item.get("title", "") or metadata.get("title", "") or ""),
            "markdown": markdown,
            "html": html,
            "text": text,
            "status": status,
            "metadata": metadata,
        }
