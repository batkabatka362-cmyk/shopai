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
            from core.adapters.browser import alibaba
            if not alibaba.is_configured():
                raise StepSkip(
                    "alibaba scraper unavailable — install playwright "
                    "or point PLAYWRIGHT_CHROMIUM_EXECUTABLE at a binary"
                )
            scraped = alibaba.scrape(context.goal.alibaba_url or "")
            if not scraped.get("title"):
                raise StepSkip(
                    f"alibaba scrape returned no title "
                    f"(url={context.goal.alibaba_url})"
                )
            payload = {
                "title": scraped.get("title", ""),
                "price_usd": float(scraped.get("price_usd", 0)),
                "supplier_url": scraped.get("supplier_url", context.goal.alibaba_url or ""),
                "gallery_urls": list(scraped.get("gallery_urls") or []),
                "attributes": dict(scraped.get("attributes") or {}),
                "_source_kind": "alibaba",
            }
            return payload

        if kind == "spy_url":
            raise StepSkip(
                "spy URL parser not implemented "
                "(needs Minea / AdSpy adapter under core/adapters/ads_spy/)"
            )

        if kind == "supplier_sku":
            return self._resolve_supplier_sku(
                str(context.goal.supplier_sku or ""),
            )

        raise StepSkip(f"unknown source kind: {kind}")

    def _resolve_supplier_sku(
        self, sourcing_id: str,
    ) -> dict[str, Any]:
        """Look up a supplier SKU directly via the CJ adapter
        (no scraping). Normalises the response into the same
        shape the manual / alibaba paths produce so downstream
        steps are source-agnostic."""
        if not sourcing_id:
            raise StepSkip(
                "supplier_sku not set on LaunchGoal",
            )
        try:
            from core.adapters.base import Capability
            from core.adapters.sourcing.cj_dropshipping import (
                CJDropshippingAdapter,
            )
        except Exception as exc:  # noqa: BLE001
            raise StepSkip(
                f"CJ adapter import failed: {exc}",
            )
        adapter = CJDropshippingAdapter()
        if not adapter.is_configured():
            raise StepSkip(
                "CJ adapter not configured "
                "(CJ_DROPSHIPPING_API_KEY missing or "
                "adapter rejected the token)",
            )
        result = adapter.execute(
            Capability.SOURCING_GET_PRODUCT,
            {"sourcing_id": sourcing_id},
        )
        if not result.ok:
            raise StepSkip(
                f"CJ get_product failed for "
                f"sourcing_id={sourcing_id}: "
                f"{getattr(result, 'error', 'unknown')}",
            )
        data = result.data or {}
        title = str(data.get("title") or "").strip()
        if not title:
            raise StepSkip(
                f"CJ returned no title for "
                f"sourcing_id={sourcing_id}",
            )
        return {
            "title": title,
            "price_usd": float(
                data.get("price_usd") or 0,
            ),
            # CJ returns a product URL via `supplier_url` when
            # present; fall back to an API reference for
            # traceability.
            "supplier_url": str(
                data.get("supplier_url")
                or data.get("product_url")
                or f"cj://product/{sourcing_id}",
            ),
            "gallery_urls": list(
                data.get("gallery_urls") or [],
            ),
            "attributes": dict(
                data.get("attributes") or {},
            ),
            "sourcing_id": sourcing_id,
            "_source_kind": "supplier_sku",
        }

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
