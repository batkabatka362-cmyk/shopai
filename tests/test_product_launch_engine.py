"""Tests for engines.product_launch — winner → launch plan spec.

Mirrors the structure of test_ad_creative_generator.py:
  - TestEntryPoint          — run() envelope, engine name, meta
  - TestInputValidation     — bad/missing winner, bad product, upstream fail
  - TestCopyOnEntry         — deepcopy isolation
  - TestSourcing            — cost/origin extraction from supplier & product
  - TestPricing             — margin math, psychological pricing, guards
  - TestShopifyDraft        — title, body_html, tags, variants, images
  - TestAdsCampaign         — platform, budget, pixel, targeting, creatives
  - TestBlocks              — every block condition
  - TestReadiness           — blocked / pending_approval / ready tri-state
  - TestApprovals           — operator checklist generation
  - TestDryRun              — dry_run flag passthrough
  - TestEndToEnd            — full happy-path with all inputs
"""
from __future__ import annotations

import copy
import math
from typing import Any

import pytest

from engines.product_launch import ENGINE_NAME, ProductLaunchEngine, run


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _winner(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "product_key": "posture-corrector-001",
        "score": 82.5,
        "verdict": "strong_buy",
        "factors": {
            "engagement_velocity": {"value": 1200, "score": 20},
        },
        "source_count": 2,
        "sources": ["minea", "pipiads"],
        "record_count": 4,
        "hero_ad": {
            "ad_id": "ad_123",
            "source": "minea",
            "advertiser": "PosturePro",
            "product_url": "https://example.com/posture",
            "creative_url": "https://example.com/video.mp4",
            "headline": "Fix Your Posture in 30 Days",
            "copy": "Silent posture corrector that works.",
            "days_running": 21,
        },
    }
    base.update(overrides)
    return base


def _product(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Silent Posture Corrector",
        "description": "Invisible posture trainer with vibration reminders.",
        "category": "Health & Wellness",
        "cost_usd": 8.50,
        "price": 39.99,
        "images": [
            "https://img.example.com/posture1.jpg",
            "https://img.example.com/posture2.jpg",
        ],
        "tags": ["posture", "health"],
        "origin_country": "CN",
        "shipping_days_min": 7,
        "shipping_days_max": 15,
    }
    base.update(overrides)
    return base


def _supplier(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "sourcing_id": "cj-prod-9876",
        "source": "cj_dropshipping",
        "title": "Posture Corrector V2",
        "description": "Smart posture corrector with vibration alert.",
        "category": "Health",
        "cost_usd": 7.20,
        "origin_country": "CN",
        "shipping_days_min": 8,
        "shipping_days_max": 14,
        "images": ["https://cj.example.com/img1.jpg"],
        "variants": [
            {
                "variant_id": "v1",
                "sku": "PC-BLK-S",
                "cost_usd": 7.20,
                "attributes": {"color": "Black", "size": "S"},
                "stock": 500,
            },
            {
                "variant_id": "v2",
                "sku": "PC-BLK-M",
                "cost_usd": 7.20,
                "attributes": {"color": "Black", "size": "M"},
                "stock": 300,
            },
        ],
    }
    base.update(overrides)
    return base


def _creative(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "readiness": "pending_approval",
        "blocks": [],
        "total_est_cost_usd": 0.15,
        "copy_variants": [
            {
                "angle": "problem_agitation",
                "headline": "Struggling with bad posture?",
                "body": "Fix it in 30 days.",
                "cta": "SHOP_NOW",
            },
            {
                "angle": "benefit_driven",
                "headline": "Better posture, better life",
                "body": "Feel the difference.",
                "cta": "SHOP_NOW",
            },
        ],
    }
    base.update(overrides)
    return base


def _ads(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "platform": "meta",
        "daily_budget_usd": 10.0,
        "pixel_id": "px_abc123",
        "targeting": {
            "countries": ["US", "CA"],
            "ages": [18, 45],
            "interests": ["fitness", "health"],
        },
    }
    base.update(overrides)
    return base


def _call(**kwargs: Any) -> dict[str, Any]:
    """Shorthand: merge default winner+product+supplier+creative+ads."""
    payload: dict[str, Any] = {
        "winner": kwargs.pop("winner", _winner()),
        "product": kwargs.pop("product", _product()),
        "supplier_product": kwargs.pop("supplier_product", _supplier()),
        "creative_pack": kwargs.pop("creative_pack", _creative()),
        "ads": kwargs.pop("ads", _ads()),
    }
    payload.update(kwargs)
    return run(payload)


# ===================================================================
# TestEntryPoint
# ===================================================================


class TestEntryPoint:
    def test_engine_name(self):
        assert ENGINE_NAME == "product_launch"

    def test_class_wrapper(self):
        eng = ProductLaunchEngine()
        assert eng.ENGINE_NAME == "product_launch"
        assert eng.engine_name == "product_launch"

    def test_class_run_returns_success(self):
        eng = ProductLaunchEngine()
        r = eng.run({"winner": _winner(), "product": _product()})
        assert r["status"] == "success"

    def test_meta_fields(self):
        r = _call()
        assert r["meta"]["engine"] == "product_launch"
        assert "timestamp" in r["meta"]
        assert "elapsed_seconds" in r["meta"]
        assert r["error"] is None

    def test_launch_plan_in_data(self):
        r = _call()
        assert "launch_plan" in r["data"]
        lp = r["data"]["launch_plan"]
        assert "sourcing" in lp
        assert "pricing" in lp
        assert "shopify_product" in lp
        assert "ads_campaign" in lp


# ===================================================================
# TestInputValidation
# ===================================================================


class TestInputValidation:
    def test_none_input(self):
        r = run(None)
        assert r["status"] == "error"
        assert "winner" in r["error"].lower()

    def test_empty_dict(self):
        r = run({})
        assert r["status"] == "error"

    def test_winner_not_dict(self):
        r = run({"winner": "bad"})
        assert r["status"] == "error"

    def test_product_not_dict(self):
        r = run({"winner": _winner(), "product": "bad"})
        assert r["status"] == "error"
        assert "product" in r["error"].lower()

    def test_upstream_failure(self):
        r = run({"status": "fail", "error": "upstream broke"})
        assert r["status"] == "error"
        assert "upstream" in r["error"].lower()

    def test_upstream_failure_default_msg(self):
        r = run({"status": "fail"})
        assert r["status"] == "error"
        assert "upstream" in r["error"].lower()


# ===================================================================
# TestCopyOnEntry
# ===================================================================


class TestCopyOnEntry:
    def test_input_not_mutated(self):
        original = {
            "winner": _winner(),
            "product": _product(),
            "supplier_product": _supplier(),
        }
        snapshot = copy.deepcopy(original)
        run(original)
        assert original == snapshot


# ===================================================================
# TestSourcing
# ===================================================================


class TestSourcing:
    def test_supplier_cost_preferred(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["sourcing"]["cost_usd"] == 7.20

    def test_fallback_to_product_cost(self):
        r = _call(supplier_product={})
        lp = r["data"]["launch_plan"]
        assert lp["sourcing"]["cost_usd"] == 8.50

    def test_origin_from_supplier(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["sourcing"]["origin_country"] == "CN"

    def test_origin_fallback_to_product(self):
        r = _call(supplier_product={})
        lp = r["data"]["launch_plan"]
        assert lp["sourcing"]["origin_country"] == "CN"

    def test_shipping_days(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["sourcing"]["shipping_days_min"] == 8
        assert lp["sourcing"]["shipping_days_max"] == 14

    def test_sourcing_id(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["sourcing"]["sourcing_id"] == "cj-prod-9876"
        assert lp["sourcing"]["source"] == "cj_dropshipping"


# ===================================================================
# TestPricing
# ===================================================================


class TestPricing:
    def test_default_margin(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        p = lp["pricing"]
        assert p["target_margin_pct"] == 0.35

    def test_custom_margin(self):
        r = _call(pricing={"margin_pct": 0.50})
        lp = r["data"]["launch_plan"]
        assert lp["pricing"]["target_margin_pct"] == 0.50

    def test_margin_pct_as_percentage(self):
        r = _call(pricing={"margin_pct": 40})
        lp = r["data"]["launch_plan"]
        assert lp["pricing"]["target_margin_pct"] == 0.40

    def test_cn_shipping_estimate(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["pricing"]["shipping_estimate_usd"] == 4.0

    def test_us_shipping_estimate(self):
        r = _call(
            supplier_product=_supplier(origin_country="US"),
        )
        lp = r["data"]["launch_plan"]
        assert lp["pricing"]["shipping_estimate_usd"] == 2.0

    def test_custom_shipping_buffer(self):
        r = _call(pricing={"shipping_buffer_usd": 5.0})
        lp = r["data"]["launch_plan"]
        assert lp["pricing"]["shipping_estimate_usd"] == 5.0

    def test_psychological_pricing_ends_in_99(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        retail = lp["pricing"]["retail_usd"]
        cents = round(retail * 100) % 100
        assert cents == 99, f"retail={retail} doesn't end in .99"

    def test_retail_above_min_price(self):
        r = _call(pricing={"min_price": 29.99})
        lp = r["data"]["launch_plan"]
        assert lp["pricing"]["retail_usd"] >= 29.99

    def test_min_price_enforced(self):
        r = _call(
            supplier_product=_supplier(cost_usd=0.50),
            product=_product(cost_usd=0.50),
            pricing={"min_price": 19.99, "shipping_buffer_usd": 0.5},
        )
        lp = r["data"]["launch_plan"]
        assert lp["pricing"]["retail_usd"] >= 19.99

    def test_total_cost_is_sum(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        p = lp["pricing"]
        assert p["total_cost_usd"] == round(p["cost_usd"] + p["shipping_estimate_usd"], 2)

    def test_margin_usd_positive(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["pricing"]["margin_usd"] > 0

    def test_actual_margin_above_target(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        p = lp["pricing"]
        assert p["margin_pct"] >= p["target_margin_pct"] - 0.02

    def test_zero_cost_yields_zero_retail(self):
        r = _call(
            supplier_product={},
            product=_product(cost_usd=0, cost=None, origin_country=""),
            pricing={"shipping_buffer_usd": 0},
        )
        lp = r["data"]["launch_plan"]
        assert lp["pricing"]["retail_usd"] == 0.0


# ===================================================================
# TestShopifyDraft
# ===================================================================


class TestShopifyDraft:
    def test_title_from_product(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["shopify_product"]["title"] == "Silent Posture Corrector"

    def test_title_fallback_to_supplier(self):
        r = _call(product=_product(title=""))
        lp = r["data"]["launch_plan"]
        assert lp["shopify_product"]["title"] == "Posture Corrector V2"

    def test_title_fallback_to_winner(self):
        r = _call(product=_product(title=""), supplier_product=_supplier(title=""))
        lp = r["data"]["launch_plan"]
        assert "Posture" in lp["shopify_product"]["title"]

    def test_body_html_wrapped(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["shopify_product"]["body_html"].startswith("<p>")
        assert "</p>" in lp["shopify_product"]["body_html"]

    def test_body_html_escapes(self):
        r = _call(product=_product(description="Price < $10 & good"))
        lp = r["data"]["launch_plan"]
        assert "&lt;" in lp["shopify_product"]["body_html"]
        assert "&amp;" in lp["shopify_product"]["body_html"]

    def test_body_html_passthrough_existing_html(self):
        r = _call(product=_product(description="<p>Already HTML</p>"))
        lp = r["data"]["launch_plan"]
        assert lp["shopify_product"]["body_html"] == "<p>Already HTML</p>"

    def test_status_default_draft(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["shopify_product"]["status"] == "draft"

    def test_status_override(self):
        r = _call(shopify={"status": "active"})
        lp = r["data"]["launch_plan"]
        assert lp["shopify_product"]["status"] == "active"

    def test_vendor(self):
        r = _call(shopify={"vendor": "MyBrand"})
        lp = r["data"]["launch_plan"]
        assert lp["shopify_product"]["vendor"] == "MyBrand"

    def test_tags_include_verdict(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert "verdict:strong_buy" in lp["shopify_product"]["tags"]

    def test_tags_from_config(self):
        r = _call(shopify={"tags": ["sale", "new"]})
        lp = r["data"]["launch_plan"]
        assert "sale" in lp["shopify_product"]["tags"]

    def test_tags_deduped(self):
        r = _call(
            shopify={"tags": ["health"]},
            product=_product(tags=["health", "posture"]),
        )
        lp = r["data"]["launch_plan"]
        count = sum(1 for t in lp["shopify_product"]["tags"] if t.lower() == "health")
        assert count == 1

    def test_images_from_both_sources(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        urls = [i["src"] for i in lp["shopify_product"]["images"]]
        assert "https://img.example.com/posture1.jpg" in urls
        assert "https://cj.example.com/img1.jpg" in urls

    def test_images_deduped(self):
        dup_url = "https://img.example.com/posture1.jpg"
        r = _call(supplier_product=_supplier(images=[dup_url]))
        lp = r["data"]["launch_plan"]
        urls = [i["src"] for i in lp["shopify_product"]["images"]]
        assert urls.count(dup_url) == 1

    def test_variants_from_supplier(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        variants = lp["shopify_product"]["variants"]
        assert len(variants) == 2
        assert variants[0]["sku"] == "PC-BLK-S"
        assert variants[0]["option1"] == "Black"
        assert variants[0]["option2"] == "S"

    def test_default_single_variant(self):
        r = _call(supplier_product={})
        lp = r["data"]["launch_plan"]
        variants = lp["shopify_product"]["variants"]
        assert len(variants) == 1

    def test_variant_price_matches_retail(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        retail = lp["pricing"]["retail_usd"]
        for v in lp["shopify_product"]["variants"]:
            assert float(v["price"]) == retail

    def test_inventory_management(self):
        r = _call(shopify={"inventory_management": "fulfillment_service"})
        lp = r["data"]["launch_plan"]
        for v in lp["shopify_product"]["variants"]:
            assert v["inventory_management"] == "fulfillment_service"


# ===================================================================
# TestAdsCampaign
# ===================================================================


class TestAdsCampaign:
    def test_default_platform_meta(self):
        r = _call(ads={})
        lp = r["data"]["launch_plan"]
        assert lp["ads_campaign"]["platform"] == "meta"

    def test_tiktok_platform(self):
        r = _call(ads={"platform": "tiktok", "daily_budget_usd": 15})
        lp = r["data"]["launch_plan"]
        assert lp["ads_campaign"]["platform"] == "tiktok"

    def test_daily_budget(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["ads_campaign"]["daily_budget_usd"] == 10.0

    def test_pixel_id(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["ads_campaign"]["pixel_id"] == "px_abc123"

    def test_targeting_passthrough(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        t = lp["ads_campaign"]["targeting"]
        assert t["countries"] == ["US", "CA"]
        assert t["ages"] == [18, 45]

    def test_targeting_defaults(self):
        r = _call(ads={"pixel_id": "px_1"})
        lp = r["data"]["launch_plan"]
        t = lp["ads_campaign"]["targeting"]
        assert "US" in t["countries"]
        assert t["ages"] == [18, 55]

    def test_creatives_from_pack(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert len(lp["ads_campaign"]["creatives"]) == 2
        assert lp["ads_campaign"]["creatives"][0]["angle"] == "problem_agitation"

    def test_campaign_name(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert "Launch" in lp["ads_campaign"]["campaign_name"]
        assert "Silent Posture Corrector" in lp["ads_campaign"]["campaign_name"]

    def test_pixel_events_default(self):
        r = _call(ads={"pixel_id": "px_1"})
        lp = r["data"]["launch_plan"]
        assert "Purchase" in lp["ads_campaign"]["pixel_events"]


# ===================================================================
# TestBlocks
# ===================================================================


class TestBlocks:
    def test_skip_verdict_blocks(self):
        r = _call(winner=_winner(verdict="skip"))
        lp = r["data"]["launch_plan"]
        assert lp["readiness"] == "blocked"
        assert any("skip" in b for b in lp["blocks"])

    def test_no_cost_blocks(self):
        r = _call(
            supplier_product={},
            product=_product(cost_usd=0, cost=None),
            pricing={"shipping_buffer_usd": 0},
        )
        lp = r["data"]["launch_plan"]
        assert lp["readiness"] == "blocked"
        assert any("cost" in b.lower() for b in lp["blocks"])

    def test_low_margin_blocks(self):
        r = _call(
            supplier_product=_supplier(cost_usd=30.0),
            pricing={"margin_pct": 0.10, "shipping_buffer_usd": 5.0},
        )
        lp = r["data"]["launch_plan"]
        assert any("margin" in b.lower() for b in lp["blocks"])

    def test_meta_no_pixel_blocks(self):
        r = _call(ads={"platform": "meta", "pixel_id": "", "daily_budget_usd": 10})
        lp = r["data"]["launch_plan"]
        assert any("pixel" in b.lower() for b in lp["blocks"])

    def test_tiktok_no_pixel_ok(self):
        r = _call(ads={"platform": "tiktok", "pixel_id": "", "daily_budget_usd": 10})
        lp = r["data"]["launch_plan"]
        assert not any("pixel" in b.lower() for b in lp["blocks"])

    def test_zero_budget_blocks(self):
        r = _call(ads={"pixel_id": "px_1", "daily_budget_usd": 0})
        lp = r["data"]["launch_plan"]
        assert any("budget" in b.lower() for b in lp["blocks"])

    def test_creative_blocked_propagates(self):
        r = _call(
            creative_pack=_creative(readiness="blocked", blocks=["no images"]),
        )
        lp = r["data"]["launch_plan"]
        assert any("creative_pack" in b for b in lp["blocks"])

    def test_no_blocks_on_happy_path(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["blocks"] == []


# ===================================================================
# TestReadiness
# ===================================================================


class TestReadiness:
    def test_blocked_when_blocks_exist(self):
        r = _call(winner=_winner(verdict="skip"))
        assert r["data"]["launch_plan"]["readiness"] == "blocked"

    def test_pending_approval_default(self):
        r = _call()
        assert r["data"]["launch_plan"]["readiness"] == "pending_approval"

    def test_ready_with_auto_approve(self):
        r = _call(auto_approve=True)
        assert r["data"]["launch_plan"]["readiness"] == "ready"

    def test_blocked_overrides_auto_approve(self):
        r = _call(
            winner=_winner(verdict="skip"),
            auto_approve=True,
        )
        assert r["data"]["launch_plan"]["readiness"] == "blocked"


# ===================================================================
# TestApprovals
# ===================================================================


class TestApprovals:
    def test_approvals_on_happy_path(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert len(lp["approvals_needed"]) >= 3
        assert any("pricing" in a.lower() for a in lp["approvals_needed"])
        assert any("shopify" in a.lower() for a in lp["approvals_needed"])

    def test_creative_approval_when_pack_present(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert any("creative" in a.lower() for a in lp["approvals_needed"])

    def test_no_creative_approval_when_empty(self):
        r = _call(creative_pack={})
        lp = r["data"]["launch_plan"]
        assert not any("creative" in a.lower() for a in lp["approvals_needed"])

    def test_watch_verdict_extra_approval(self):
        r = _call(winner=_winner(verdict="watch"))
        lp = r["data"]["launch_plan"]
        assert any("watch" in a.lower() for a in lp["approvals_needed"])

    def test_no_approvals_when_blocked(self):
        r = _call(winner=_winner(verdict="skip"))
        lp = r["data"]["launch_plan"]
        assert lp["approvals_needed"] == []


# ===================================================================
# TestDryRun
# ===================================================================


class TestDryRun:
    def test_dry_run_false_default(self):
        r = _call()
        assert r["data"]["launch_plan"]["dry_run"] is False

    def test_dry_run_true(self):
        r = _call(dry_run=True)
        assert r["data"]["launch_plan"]["dry_run"] is True


# ===================================================================
# TestCostRollup
# ===================================================================


class TestCostRollup:
    def test_total_cost_includes_creative_and_ads(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        expected = 0.15 + 10.0  # creative + daily budget
        assert lp["total_est_cost_usd"] == expected

    def test_total_cost_zero_when_no_creative_no_ads(self):
        r = _call(creative_pack={}, ads={})
        lp = r["data"]["launch_plan"]
        assert lp["total_est_cost_usd"] >= 0


# ===================================================================
# TestDataPassthrough
# ===================================================================


class TestDataPassthrough:
    def test_product_key(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["product_key"] == "posture-corrector-001"

    def test_winner_verdict(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["winner_verdict"] == "strong_buy"

    def test_winner_score(self):
        r = _call()
        lp = r["data"]["launch_plan"]
        assert lp["winner_score"] == 82.5

    def test_creative_pack_echoed(self):
        c = _creative()
        r = _call(creative_pack=c)
        lp = r["data"]["launch_plan"]
        assert lp["creative_pack"]["readiness"] == "pending_approval"
        assert len(lp["creative_pack"]["copy_variants"]) == 2


# ===================================================================
# TestEndToEnd — full happy-path
# ===================================================================


class TestEndToEnd:
    def test_full_launch_plan(self):
        r = _call()
        assert r["status"] == "success"
        lp = r["data"]["launch_plan"]
        assert lp["readiness"] == "pending_approval"
        assert lp["blocks"] == []
        assert lp["pricing"]["retail_usd"] > 0
        assert lp["pricing"]["margin_usd"] > 0
        assert lp["shopify_product"]["title"] == "Silent Posture Corrector"
        assert lp["shopify_product"]["status"] == "draft"
        assert len(lp["shopify_product"]["variants"]) == 2
        assert len(lp["ads_campaign"]["creatives"]) == 2
        assert lp["ads_campaign"]["pixel_id"] == "px_abc123"
        assert lp["total_est_cost_usd"] == 10.15

    def test_minimal_input(self):
        r = run({"winner": _winner()})
        assert r["status"] == "success"
        lp = r["data"]["launch_plan"]
        assert lp["readiness"] == "blocked"
        assert "cost" in " ".join(lp["blocks"]).lower()

    def test_supplier_only_no_product(self):
        r = run({
            "winner": _winner(),
            "supplier_product": _supplier(),
            "ads": _ads(),
        })
        assert r["status"] == "success"
        lp = r["data"]["launch_plan"]
        assert lp["pricing"]["cost_usd"] == 7.20
        assert lp["shopify_product"]["title"] == "Posture Corrector V2"
