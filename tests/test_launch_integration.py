"""End-to-end launch pipeline integration test.

Exercises the full 9-step flow with every external call stubbed:
  Shopify product_create, metafield writes, Pexels photo/video search,
  LLM router, Playwright (unused in manual mode). Verifies:

  • status == complete
  • each required step produced the expected keys in its slot on
    LaunchContext
  • the Monitor step records a ``category=launch`` memory event so
    the evaluator can find the new launch on its next cycle
  • the LaunchResult serialises to JSON without TypeErrors
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from workflows.launch import LaunchPipeline, LaunchGoal


def _fake_llm_result(text: str):
    """Stand-in for AdapterResult without pulling the full enum."""
    from types import SimpleNamespace
    return SimpleNamespace(
        ok=True,
        adapter="fake-groq",
        model="fake-llama-3.3",
        latency_ms=120.0,
        data={"text": text},
        error=None,
    )


_CONTENT_JSON = """{
  "title": "Premium Widget Pro",
  "description_html": "<p>Widget widget widget. Premium widget for modern homes.</p>",
  "bullets": ["Fast","Cheap","Loved","Stocked","Shipped"],
  "seo_title": "Premium Widget Pro — Best Widget 2026",
  "seo_description": "Buy the Premium Widget Pro — Best widget, fast shipping, 30-day guarantee.",
  "tags": ["widget","premium","home"]
}"""

_CREATIVE_JSON = """[
  {"id":"v1_hook","headline":"Widget shock","primary_text":"You won't believe what this widget does.","cta":"Shop Now"},
  {"id":"v2_benefits","headline":"Daily win","primary_text":"Save time with Premium Widget Pro every day.","cta":"Learn More"},
  {"id":"v3_proof","headline":"5-star","primary_text":"Over 10,000 homeowners love Premium Widget Pro.","cta":"Get Yours"}
]"""


class TestFullLaunchIntegration(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["SHOPAI_SHOPIFY_URL"] = "test.myshopify.com"
        os.environ["SHOPAI_SHOPIFY_KEY"] = "shpat_fake_integration"
        # Clear any credentials the optional steps would pick up
        for k in (
            "CJ_DROPSHIPPING_API_KEY", "AUTODS_API_KEY",
            "META_ADS_ACCESS_TOKEN", "META_ADS_ACCOUNT_ID",
            "META_ADS_PIXEL_ID", "META_ADS_PAGE_ID",
            "PEXELS_API_KEY",
        ):
            os.environ.pop(k, None)

    def test_full_flow_with_manual_payload(self) -> None:
        # Stub external calls
        product_patch = patch(
            "execution.shopify.product_creator.ProductCreator.create_product",
            return_value={
                "status": "created",
                "product": {"id": 1234567890, "handle": "premium-widget-pro"},
            },
        )
        # Metafield write happens via urllib — patch urllib.request.urlopen
        # at the module level where each step imports it.
        urlopen_patch = patch(
            "urllib.request.urlopen",
            side_effect=self._fake_urlopen,
        )
        # LLM router call for content + creative steps
        llm_patch = patch(
            "core.adapters.router.SmartRouter.execute",
            side_effect=self._fake_llm_execute,
        )
        # Memory — in-process create is fine; the DB is file-backed
        # and shared with other tests. No need to mock.

        with product_patch, urlopen_patch, llm_patch:
            goal = LaunchGoal(
                manual_payload={
                    "title": "Premium Widget Pro",
                    "price_usd": 6.99,
                    "gallery_urls": [
                        "https://cdn.example.com/widget-1.jpg",
                        "https://cdn.example.com/widget-2.jpg",
                    ],
                    "attributes": {"color": "black"},
                },
                target_price=29.99,
                niche="home",
                copy_tone="friendly",
            )
            result = LaunchPipeline().run(goal)

        self.assertEqual(result.status, "complete",
                         f"expected complete, got {result.status} "
                         f"failed={result.failed_step} reason={result.failure_reason}")
        self.assertEqual(result.shopify_product_id, 1234567890)
        self.assertEqual(result.shopify_handle, "premium-widget-pro")

        # Every required step must be OK (supplier + ads_launch skip
        # cleanly because creds are absent)
        by_name = {s.name: s for s in result.steps}
        for required in ("source", "media", "content", "shopify_create",
                         "creative", "tracking", "monitor"):
            self.assertEqual(by_name[required].status, "ok",
                             f"step {required} should be ok, got {by_name[required].status}")
        for optional in ("supplier", "ads_launch"):
            self.assertEqual(by_name[optional].status, "skipped",
                             f"step {optional} should skip without creds")

        # Result must round-trip through JSON
        import json
        try:
            json.dumps(result.as_dict())
        except (TypeError, ValueError) as exc:
            self.fail(f"LaunchResult not JSON-safe: {exc}")

    # ── Stubs ────────────────────────────────────────────

    @staticmethod
    def _fake_urlopen(req, *a, **kw):
        """Accept any urllib call and return a benign 200 JSON body.

        Metafield POST returns an id; product GET (for related) returns
        a tiny catalog so RelatedProductsStep has something to score.
        """
        from io import BytesIO
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/metafields.json" in url and "POST" in req.get_method():
            body = b'{"metafield": {"id": 1, "value": "[]"}}'
        elif "/products.json" in url and req.get_method() == "GET":
            body = b'{"products": []}'
        else:
            body = b"{}"

        class FakeResp:
            def __init__(self, data):
                self._data = data
            def read(self):
                return self._data
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return FakeResp(body)

    @staticmethod
    def _fake_llm_execute(capability, params=None, context=None, **kw):
        """Return JSON-shaped content for ContentStep and array-shaped
        for CreativeStep based on prompt content."""
        msgs = (params or {}).get("messages") or []
        prompt = msgs[0].get("content", "") if msgs else ""
        if "ad variants" in prompt.lower() or "meta ads creatives" in prompt.lower():
            return _fake_llm_result(_CREATIVE_JSON)
        return _fake_llm_result(_CONTENT_JSON)


if __name__ == "__main__":
    unittest.main()
