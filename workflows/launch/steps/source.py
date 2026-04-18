"""Step 1 — Source resolution.

Resolve the owner's input pointer (Alibaba URL / spy URL / supplier SKU /
manual payload) into a normalized ``source`` dict containing:

    title, price_usd, supplier_url, gallery_urls, attributes, raw_html

Per CLAUDE.md §4 — Research First — we prefer adapters / public APIs to
scratch scraping:

    Alibaba: no public API → Playwright (browser adapter, stub today)
    Spy URL (Minea / AdSpy): public API per provider
    Supplier SKU: CJ / AutoDS API direct lookup
    Manual:      pass-through, owner-supplied dict

When the corresponding adapter is not yet wired (90 % of today's case),
the step raises ``StepSkip`` carrying a TODO so the pipeline still runs
end-to-end with placeholder data the downstream steps can render.
"""
from __future__ import annotations

from typing import Any

from ..context import LaunchContext
from ._base import Step, StepSkip


class SourceStep(Step):
    name = "source"

    def execute(self, context: LaunchContext) -> dict[str, Any]:
        kind = context.goal.source_kind()

        if kind == "manual":
            payload = context.goal.manual_payload or {}
            if not payload.get("title"):
                raise StepSkip("manual_payload missing 'title'")
            return self._normalize(payload)

        if kind == "alibaba":
            # TODO(brain): wire core/adapters/browser/ Playwright adapter
            # to scrape Alibaba product detail pages. Until then surface
            # a placeholder so downstream steps can be exercised.
            raise StepSkip(
                "alibaba scraper not implemented "
                "(needs core/adapters/browser/playwright bootstrap)"
            )

        if kind == "spy_url":
            raise StepSkip(
                "spy URL parser not implemented "
                "(needs Minea / AdSpy adapter under core/adapters/ads_spy/)"
            )

        if kind == "supplier_sku":
            # TODO(brain): wire core/adapters/sourcing/cj_dropshipping.py
            # to look up SKU directly without scraping.
            raise StepSkip(
                "supplier SKU lookup not implemented "
                "(needs CJ_DROPSHIPPING_API_KEY + adapter wire-up)"
            )

        raise StepSkip(f"unknown source kind: {kind}")

    @staticmethod
    def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": payload.get("title", ""),
            "price_usd": float(payload.get("price_usd", 0)),
            "supplier_url": payload.get("supplier_url", ""),
            "gallery_urls": list(payload.get("gallery_urls", [])),
            "attributes": dict(payload.get("attributes", {})),
            "_source_kind": "manual",
        }
