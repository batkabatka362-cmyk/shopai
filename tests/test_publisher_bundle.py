"""Publisher bundle tests."""
from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock

from execution.launch import publisher_bundle as pb


def _winner(**kw):
    base = dict(
        title="Pet Slow-Feeder Bowl",
        price=29.99,
        image_url="https://cdn.example/pet-bowl.jpg",
        margin_pct=0.65,
        source="aliexpress",
    )
    base.update(kw)
    return base


def _request(live=False, **kw):
    defaults = dict(
        winner=_winner(),
        shop_url="example.myshopify.com",
        api_key="test_tok",
        ad_budget_daily=20.0,
        ad_objective="OUTCOME_SALES",
        platform="facebook",
        meta_account_id="act_12345",
        live=live,
    )
    defaults.update(kw)
    return pb.LaunchRequest(**defaults)


class _FakeContent:
    def ad_copy(self, product, platform="facebook"):
        return {
            "platform": platform,
            "headline": f"{product['title']} headline",
            "body": f"Shop {product['title']} today!",
            "cta": "Shop Now",
        }


class _FakeProducts:
    def __init__(self, status="created", product_id="prod_99",
                 handle="pet-slow-feeder-bowl"):
        self._status = status
        self._id = product_id
        self._handle = handle
        self.calls: list[dict] = []

    def create_product(self, shop_url, api_key, payload):
        self.calls.append({
            "shop_url": shop_url,
            "api_key": api_key,
            "payload": payload,
        })
        if self._status == "created":
            return {
                "status": "created",
                "product": {
                    "id": self._id,
                    "handle": self._handle,
                },
            }
        return {
            "status": "error",
            "error": "forced failure",
        }


class _FakeAds:
    def __init__(self, success=True):
        self._success = success

    def execute(self, capability, params):
        from core.adapters.base import AdapterResult
        from core.adapters.errors import AdapterError
        if self._success:
            return AdapterResult.success(
                adapter="fake_ads",
                capability=capability.value,
                data={"campaign_id": "camp_abc"},
                raw={},
            )
        return AdapterResult.failure(
            adapter="fake_ads",
            capability=capability.value,
            error=AdapterError(
                "fake_ads", "ad denied",
            ),
            raw={},
        )


class _FakeOutcomes:
    def __init__(self):
        self.recorded = []
    def record(self, event):
        self.recorded.append(event)
        return MagicMock(event_id="e1")


class _FakeRationale:
    def __init__(self):
        self.started = []
        self.added = []
        self.committed = []
    def start(self, *, decision_id, summary):
        self.started.append((decision_id, summary))
        return MagicMock()
    def add(self, decision_id, **kw):
        self.added.append((decision_id, kw))
        return MagicMock()
    def commit(self, decision_id):
        self.committed.append(decision_id)
        return MagicMock()


class TestRequest(unittest.TestCase):
    def test_blank_winner_raises(self):
        with self.assertRaises(ValueError):
            pb.LaunchRequest(
                winner={},
                shop_url="s.myshopify.com",
                api_key="tok",
            )

    def test_blank_shop_raises(self):
        with self.assertRaises(ValueError):
            pb.LaunchRequest(
                winner=_winner(),
                shop_url="",
                api_key="tok",
            )

    def test_live_requires_api_key(self):
        with self.assertRaises(ValueError):
            pb.LaunchRequest(
                winner=_winner(),
                shop_url="s.myshopify.com",
                api_key="",
                live=True,
            )

    def test_bad_budget_raises(self):
        with self.assertRaises(ValueError):
            pb.LaunchRequest(
                winner=_winner(),
                shop_url="s.myshopify.com",
                api_key="tok",
                ad_budget_daily=0,
            )

    def test_bad_platform_raises(self):
        with self.assertRaises(ValueError):
            pb.LaunchRequest(
                winner=_winner(),
                shop_url="s.myshopify.com",
                api_key="tok",
                platform="snapchat",
            )

    def test_decision_id_auto(self):
        r = _request()
        self.assertTrue(r.resolved_decision_id.startswith("dec_"))


class TestDryRun(unittest.TestCase):
    """When live=False (or ENV not set), every real write is skipped.
    This is the default and the safe mode."""

    def setUp(self):
        self._orig = os.environ.pop(
            "SHOPAI_ENABLE_LIVE_EXECUTION", None,
        )
        self.bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProducts(),
            ad_adapter=_FakeAds(),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=_FakeRationale(),
        )

    def tearDown(self):
        if self._orig is not None:
            os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = self._orig

    def test_dry_run_completes_all_steps(self):
        result = self.bundle.launch(_request(live=False))
        self.assertTrue(result.ok)
        self.assertTrue(result.dry_run)
        step_names = [s.name for s in result.steps]
        self.assertIn("generate_copy", step_names)
        self.assertIn("create_product", step_names)
        self.assertIn("launch_campaign", step_names)

    def test_dry_run_tracking_url_has_decision_id(self):
        result = self.bundle.launch(_request(live=False))
        self.assertIn(
            f"shopai_decision_id={result.decision_id}",
            result.tracking_url,
        )
        self.assertIn("utm_campaign=", result.tracking_url)

    def test_dry_run_skips_live_even_when_flag_on(self):
        os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
        # live=False on request → still dry_run
        result = self.bundle.launch(_request(live=False))
        self.assertTrue(result.dry_run)


class TestLivePath(unittest.TestCase):
    """live=True + ENV=1 ⇒ real writes. Fakes verify handoff."""

    def setUp(self):
        self._orig = os.environ.get(
            "SHOPAI_ENABLE_LIVE_EXECUTION",
        )
        os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
        self.content = _FakeContent()
        self.products = _FakeProducts()
        self.ads = _FakeAds(success=True)
        self.outcomes = _FakeOutcomes()
        self.rationale = _FakeRationale()
        self.bundle = pb.PublisherBundle(
            content_generator=self.content,
            product_creator=self.products,
            ad_adapter=self.ads,
            outcome_recorder=self.outcomes,
            rationale_builder=self.rationale,
        )

    def tearDown(self):
        if self._orig is None:
            os.environ.pop(
                "SHOPAI_ENABLE_LIVE_EXECUTION", None,
            )
        else:
            os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = self._orig

    def test_happy_path_full_writes(self):
        result = self.bundle.launch(_request(live=True))
        self.assertTrue(result.ok, result.note)
        self.assertFalse(result.dry_run)
        self.assertEqual(result.product_id, "prod_99")
        self.assertEqual(result.campaign_id, "camp_abc")
        # Tracking URL carries decision_id
        self.assertIn(
            result.decision_id, result.tracking_url,
        )
        # Outcome recorder got the at-launch event
        self.assertEqual(len(self.outcomes.recorded), 1)
        self.assertEqual(
            self.outcomes.recorded[0].kind, "launch",
        )
        # Rationale was started + committed
        self.assertEqual(len(self.rationale.started), 1)
        self.assertEqual(len(self.rationale.committed), 1)


class TestFailures(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.get(
            "SHOPAI_ENABLE_LIVE_EXECUTION",
        )
        os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"

    def tearDown(self):
        if self._orig is None:
            os.environ.pop(
                "SHOPAI_ENABLE_LIVE_EXECUTION", None,
            )
        else:
            os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = self._orig

    def test_product_creation_failure_aborts(self):
        bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProducts(status="error"),
            ad_adapter=_FakeAds(),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=_FakeRationale(),
        )
        result = bundle.launch(_request(live=True))
        self.assertFalse(result.ok)
        # launch_campaign never ran
        names = [s.name for s in result.steps]
        self.assertNotIn("launch_campaign", names)

    def test_campaign_failure_compensates_unpublish(self):
        bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProducts(),
            ad_adapter=_FakeAds(success=False),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=_FakeRationale(),
        )
        result = bundle.launch(_request(live=True))
        self.assertFalse(result.ok)
        names = [s.name for s in result.steps]
        self.assertIn("launch_campaign", names)
        # Compensation step attempted (may not succeed without
        # ProductUpdater, but must appear)
        self.assertIn("compensate_unpublish", names)


class TestTrackingURL(unittest.TestCase):
    def test_http_prefix_auto(self):
        url = pb._tracking_url(
            "store.myshopify.com", "slug", "dec_123",
        )
        self.assertTrue(url.startswith("https://"))

    def test_preserves_existing_scheme(self):
        url = pb._tracking_url(
            "http://dev.local", "slug", "dec_123",
        )
        self.assertTrue(url.startswith("http://"))

    def test_includes_all_utm_params(self):
        url = pb._tracking_url(
            "s.myshopify.com", "slug", "dec_x",
        )
        for key in (
            "shopai_decision_id=dec_x",
            "utm_source=shopai",
            "utm_medium=meta_ads",
            "utm_campaign=dec_x",
        ):
            self.assertIn(key, url)


class TestQueries(unittest.TestCase):
    def setUp(self):
        self.bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProducts(),
            ad_adapter=_FakeAds(),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=_FakeRationale(),
        )

    def test_recent_and_stats(self):
        self.bundle.launch(_request())
        self.bundle.launch(_request())
        self.assertEqual(len(self.bundle.recent()), 2)
        s = self.bundle.stats()
        self.assertEqual(s["launches"], 2)
        self.assertEqual(s["success_rate"], 1.0)
        self.assertEqual(s["dry_run_count"], 2)

    def test_reset(self):
        self.bundle.launch(_request())
        self.assertEqual(self.bundle.reset(), 1)


class TestSEOEnrichment(unittest.TestCase):
    """S3-4 wire-in: publisher_bundle fills SEO fields on Shopify
    product create, and includes the schema.org + merchant feed
    bundle in the step log."""

    def setUp(self):
        self._orig = os.environ.pop(
            "SHOPAI_ENABLE_LIVE_EXECUTION", None,
        )
        self.products = _FakeProducts()
        self.bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=self.products,
            ad_adapter=_FakeAds(),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=_FakeRationale(),
        )

    def tearDown(self):
        if self._orig is not None:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = self._orig

    def test_dry_run_exposes_seo_in_step_data(self):
        result = self.bundle.launch(_request(live=False))
        create_step = next(
            s for s in result.steps
            if s.name == "create_product"
        )
        seo = create_step.data.get("seo")
        self.assertIsNotNone(seo)
        self.assertIn("meta_title", seo)
        self.assertIn("schema_org_jsonld", seo)
        self.assertIn("merchant_feed_entry", seo)

    def test_dry_run_payload_carries_meta_tags(self):
        result = self.bundle.launch(_request(live=False))
        create_step = next(
            s for s in result.steps
            if s.name == "create_product"
        )
        payload = create_step.data["payload"]
        self.assertIn(
            "metafields_global_title_tag", payload,
        )
        self.assertIn(
            "metafields_global_description_tag", payload,
        )
        self.assertIn("seo", payload)
        # Keywords populated into tags when extracted
        self.assertIn("tags", payload)

    def test_live_path_payload_carries_seo_fields(self):
        try:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = "1"
            self.bundle.launch(_request(live=True))
        finally:
            os.environ.pop(
                "SHOPAI_ENABLE_LIVE_EXECUTION", None,
            )
        # The fake product creator captured the payload
        self.assertTrue(self.products.calls)
        last_payload = self.products.calls[-1]["payload"]
        self.assertIn(
            "metafields_global_title_tag",
            last_payload,
        )
        self.assertTrue(
            last_payload["metafields_global_title_tag"],
        )


class TestSchemaStackWire(unittest.TestCase):
    """Wave A3 wiring — schema stack emitted as Shopify product
    metafield JSON-LD."""

    def setUp(self):
        self._orig = os.environ.pop(
            "SHOPAI_ENABLE_LIVE_EXECUTION", None,
        )
        self.bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProducts(),
            ad_adapter=_FakeAds(),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=_FakeRationale(),
        )

    def tearDown(self):
        if self._orig is not None:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = self._orig

    def test_dry_run_payload_has_jsonld_metafield(self):
        result = self.bundle.launch(_request(live=False))
        step = next(
            s for s in result.steps
            if s.name == "create_product"
        )
        metafields = (
            step.data.get("payload", {}).get("metafields", [])
        )
        jsonld_meta = next(
            (
                m for m in metafields
                if m.get("namespace") == "shopai"
                and m.get("key") == "jsonld"
            ),
            None,
        )
        self.assertIsNotNone(jsonld_meta)
        self.assertIn(
            "schema.org", jsonld_meta["value"],
        )
        self.assertIn(
            "Product", jsonld_meta["value"],
        )

    def test_jsonld_contains_author_entity(self):
        result = self.bundle.launch(_request(live=False))
        step = next(
            s for s in result.steps
            if s.name == "create_product"
        )
        metafields = (
            step.data.get("payload", {}).get("metafields", [])
        )
        jsonld = next(
            (
                m["value"] for m in metafields
                if m.get("namespace") == "shopai"
                and m.get("key") == "jsonld"
            ),
            "",
        )
        self.assertIn("#publisher", jsonld)


class TestEUAIActGateWire(unittest.TestCase):
    """Wave A1 wiring — publisher_bundle calls
    EUAIActGate.verify() on every ai_creative when EU market
    is declared."""

    def setUp(self):
        self._orig = os.environ.pop(
            "SHOPAI_ENABLE_LIVE_EXECUTION", None,
        )
        self.bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProducts(),
            ad_adapter=_FakeAds(),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=_FakeRationale(),
        )

    def tearDown(self):
        if self._orig is not None:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = self._orig

    def test_no_ai_creatives_skips_cleanly(self):
        result = self.bundle.launch(_request(live=False))
        step = next(
            s for s in result.steps
            if s.name == "eu_ai_compliance"
        )
        self.assertEqual(step.status, "success")
        self.assertIn(
            "no AI creatives", step.data.get("note", ""),
        )

    def test_eu_target_with_valid_creative_passes(self):
        req = _request(
            live=False,
            target_markets=("DE",),
            ai_creatives=(
                {
                    "asset_id": "ad1",
                    "media_kind": "image",
                    "c2pa": {
                        "creator": "ShopAI",
                        "generator_model": "fal/kling",
                        "created_at_iso": "2026-04-20",
                        "ai_generated": True,
                    },
                    "disclosure_text": (
                        "This ad is AI-generated."
                    ),
                },
            ),
        )
        result = self.bundle.launch(req)
        step = next(
            s for s in result.steps
            if s.name == "eu_ai_compliance"
        )
        self.assertEqual(step.status, "success")
        self.assertTrue(result.ok)

    def test_eu_target_with_missing_c2pa_blocks_launch(self):
        req = _request(
            live=False,
            target_markets=("FR",),
            ai_creatives=(
                {
                    "asset_id": "bad",
                    "media_kind": "video",
                    "disclosure_text": "AI made this.",
                    # no c2pa
                },
            ),
        )
        result = self.bundle.launch(req)
        self.assertFalse(result.ok)
        self.assertIn("compliance", result.note)
        # launch_campaign should NOT have run
        names = [s.name for s in result.steps]
        self.assertNotIn(
            "launch_campaign", names,
        )

    def test_non_eu_with_missing_c2pa_advisory_passes(self):
        req = _request(
            live=False,
            target_markets=("US",),
            ai_creatives=(
                {
                    "asset_id": "us_ad",
                    "disclosure_text": (
                        "AI-generated content."
                    ),
                    # no c2pa; advisory only for non-EU
                },
            ),
        )
        result = self.bundle.launch(req)
        step = next(
            s for s in result.steps
            if s.name == "eu_ai_compliance"
        )
        self.assertEqual(step.status, "success")
        self.assertTrue(result.ok)


class TestDict(unittest.TestCase):
    def test_step_serialises(self):
        step = pb.StepLog(
            name="x", status="success",
            data={"k": "v"}, ts=1.0,
        )
        d = step.as_dict()
        self.assertEqual(d["name"], "x")

    def test_result_serialises(self):
        bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProducts(),
            ad_adapter=_FakeAds(),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=_FakeRationale(),
        )
        result = bundle.launch(_request())
        d = result.as_dict()
        self.assertIn("tracking_url", d)
        self.assertIn("steps", d)


if __name__ == "__main__":
    unittest.main()
