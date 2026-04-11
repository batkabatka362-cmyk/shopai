"""FirecrawlAdapter — Firecrawl web scraper.

Wave 1 extension — the FIRST adapter for Capability.SCRAPE_PAGE.
Before this commit, the capability was declared in the enum but
no adapter implemented it, so the router raised
NoAdapterAvailable on every request. Competitive-intel decisions
(price monitoring, content reconnaissance, new-product
detection) all need a page reader — this adapter is the
mechanical hand that talks to one.

Why Firecrawl:

  * **JavaScript-aware** — headless Chrome renders the page so
    React/Vue/SPA storefronts work out of the box. DDGS and
    the LLM adapters can't do this on their own.
  * **Free tier for testing** — 500 pages/month on the free
    plan, sufficient for the autonomous loop's regression tests
    and a small production probe.
  * **Single REST endpoint** — ``POST /v0/scrape`` takes a
    compact JSON body and returns markdown + html + metadata
    in one call. No SDK, no webhook dance.

Auth: static API key in ``Authorization: Bearer`` header —
``FIRECRAWL_API_KEY``. Already wired into ``ENV_ALIASES`` from
an earlier session, so this adapter reuses it verbatim.

Endpoint used:

  * ``POST /v0/scrape``

Cost: Firecrawl's paid tier is roughly $0.002/page-scrape
($16/month for 10K pages). The adapter sets ``cost_per_call =
0.002`` as a conservative default so the router's budget
optimiser sees scraping spend separately from LLM/image spend.
Free-tier users pay $0 and the ``cost_usd`` field still
represents the marginal paid cost — fine for budgeting.

Reference: https://docs.firecrawl.dev/api-reference/endpoint/scrape
"""
from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ._base import ScraperBaseAdapter


class FirecrawlAdapter(ScraperBaseAdapter):
    name = "firecrawl"
    base_url = "https://api.firecrawl.dev"
    config_alias = "firecrawl"

    # Only scraper wired today. Pin priority high so future
    # alternatives (Jina Reader, Apify) stay secondary unless an
    # operator explicitly prefers them via RouteContext.prefer.
    priority = 80
    cost_per_call = 0.002

    # ── URL / auth ────────────────────────────────────────────

    def _scrape_url(self) -> str:
        return f"{self.base_url}/v0/scrape"

    # ── Payload translation ──────────────────────────────────

    def _build_scrape_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Firecrawl v0 expects::

            {
                "url": "https://...",
                "pageOptions": {
                    "onlyMainContent":  true,
                    "includeTags":      ["article", "main"],
                    "excludeTags":      ["nav", "footer"],
                    "waitFor":          2000
                },
                "extractorOptions": {
                    "mode": "markdown"
                }
            }

        We always ask for markdown as the primary format because
        downstream LLM consumers parse it most cheaply; html is
        only added when the caller explicitly requests it.
        """
        body: dict[str, Any] = {"url": params["url"]}

        page_options: dict[str, Any] = {}
        if params.get("only_main_content") is not None:
            page_options["onlyMainContent"] = bool(
                params["only_main_content"],
            )
        include_tags = params.get("include_tags")
        if include_tags:
            page_options["includeTags"] = list(include_tags)
        exclude_tags = params.get("exclude_tags")
        if exclude_tags:
            page_options["excludeTags"] = list(exclude_tags)
        wait_for = params.get("wait_for")
        if wait_for is not None:
            page_options["waitFor"] = int(wait_for)

        if page_options:
            body["pageOptions"] = page_options

        # formats is a caller hint; Firecrawl v0 returns both
        # markdown and html by default, so we only translate it
        # into pageOptions.includeHtml when html is requested
        # AND markdown alone would have been the default.
        formats = params.get("formats") or []
        if "html" in formats:
            body.setdefault("pageOptions", {})["includeHtml"] = True

        return body

    # ── Response parsing ──────────────────────────────────────

    def _parse_scrape_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Firecrawl wraps the real payload in a ``{success, data}``
        envelope::

            {
                "success": true,
                "data": {
                    "markdown": "...",
                    "html":     "...",
                    "metadata": {
                        "title":       "...",
                        "description": "...",
                        "sourceURL":   "...",
                        "statusCode":  200
                    }
                }
            }

        We flatten it to the normalised shape so consumers never
        need to touch the envelope.
        """
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"scrape response not a dict: {type(raw).__name__}",
            )

        if raw.get("success") is False:
            # Firecrawl sometimes returns 200 with success=false
            # (e.g. robots.txt disallows, page blocked). Surface
            # as a generic AdapterError so the router records a
            # failure metric instead of a phantom "success".
            err_msg = str(raw.get("error", "") or "scrape unsuccessful")
            raise AdapterError(
                self.name, f"firecrawl returned success=false: {err_msg}",
            )

        data = raw.get("data") or raw  # tolerate flat responses
        if not isinstance(data, dict):
            raise AdapterError(
                self.name,
                f"scrape data not a dict: {type(data).__name__}",
            )

        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        markdown = str(data.get("markdown", "") or "")
        html = str(data.get("html", "") or "")
        # Prefer the content field if Firecrawl emits one;
        # otherwise fall back to markdown stripped of headers.
        text = str(
            data.get("content", "") or data.get("text", "") or markdown,
        )

        return {
            "url": str(
                metadata.get("sourceURL", "")
                or params.get("url", ""),
            ),
            "title": str(metadata.get("title", "") or ""),
            "markdown": markdown,
            "html": html,
            "text": text,
            "status": int(metadata.get("statusCode", 0) or 0),
            "metadata": metadata,
        }
