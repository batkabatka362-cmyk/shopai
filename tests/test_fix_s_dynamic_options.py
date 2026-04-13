"""Regression tests for Fix S: context-aware action
generation in ``DecisionEngine._generate_options``.

Pre-fix, the option generator produced a fixed 2-3 option
set per category from hand-coded if-chains:

  * pricing: keep_price / lower_10pct / raise_10pct
  * product: keep / add_similar / remove_underperformer
  * marketing: email_campaign / social_media / paid_ads

Rich signals in ``input_data`` (inventory surplus, missing
images, very thin margin) and ``context`` (competitor
alerts, intel strategies) were ignored. The brain could
never recommend bundling even when inventory was
overstocked, or refresh_images even when a product had no
image URL.

Core audit wave-3 #5 flagged this as the #5 MEDIUM
weakness. Fix S adds CONDITIONAL options that only fire
when the situation indicates they apply:

  1. pricing: ``bundle_suggestion`` when inventory_quantity
     >= 30 (overstock hint).
  2. pricing: ``match_competitor`` when
     ``context["competitor_alerts"]`` is non-empty.
  3. product: ``refresh_images`` when data's image_url is
     falsy.
  4. product: ``archive_low_margin`` when computed margin
     < 0.15.

The generator still returns the baseline options; Fix S
adds on top of them, never removes. DecisionEngine scoring
and the Fix H attribution trail consume the new options
exactly like the hard-coded ones.
"""
from __future__ import annotations

import pytest


class TestPricingDynamicOptions:
    def test_overstock_triggers_bundle_suggestion(self):
        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = eng._generate_options(
            "pricing",
            {"price": 50, "cost": 20, "inventory_quantity": 50},
            context={},
        )
        actions = [o["action"] for o in options]
        assert "bundle_suggestion" in actions, (
            f"overstock should produce bundle_suggestion; "
            f"got {actions}"
        )

    def test_low_inventory_skips_bundle(self):
        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = eng._generate_options(
            "pricing",
            {"price": 50, "cost": 20, "inventory_quantity": 5},
            context={},
        )
        actions = [o["action"] for o in options]
        assert "bundle_suggestion" not in actions

    def test_competitor_alert_triggers_match_competitor(self):
        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = eng._generate_options(
            "pricing",
            {"price": 50, "cost": 20, "inventory_quantity": 10},
            context={"competitor_alerts": ["competitor dropped to $45"]},
        )
        actions = [o["action"] for o in options]
        assert "match_competitor" in actions

    def test_no_competitor_alert_skips_match(self):
        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = eng._generate_options(
            "pricing",
            {"price": 50, "cost": 20},
            context={},
        )
        actions = [o["action"] for o in options]
        assert "match_competitor" not in actions

    def test_baseline_pricing_options_still_present(self):
        """Fix S adds options, never removes. The baseline
        keep_price / lower_10pct / raise_10pct must still
        fire under existing conditions."""
        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = eng._generate_options(
            "pricing",
            {"price": 100, "cost": 40},  # margin=0.6
            context={},
        )
        actions = {o["action"] for o in options}
        assert "keep_price" in actions
        assert "lower_10pct" in actions  # margin > 0.5
        assert "raise_10pct" in actions  # margin < 0.7


class TestProductDynamicOptions:
    def test_missing_image_triggers_refresh_images(self):
        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = eng._generate_options(
            "product",
            {"id": "p1", "name": "Widget", "price": 50,
             "cost": 20, "image_url": ""},
            context={},
        )
        actions = [o["action"] for o in options]
        assert "refresh_images" in actions

    def test_present_image_skips_refresh_images(self):
        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = eng._generate_options(
            "product",
            {"id": "p1", "name": "Widget", "price": 50,
             "cost": 20, "image_url": "https://cdn.example/p1.jpg"},
            context={},
        )
        actions = [o["action"] for o in options]
        assert "refresh_images" not in actions

    def test_thin_margin_triggers_archive_option(self):
        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = eng._generate_options(
            "product",
            {"id": "p1", "name": "Widget", "price": 10, "cost": 9},
            context={},
        )
        actions = [o["action"] for o in options]
        assert "archive_low_margin" in actions

    def test_healthy_margin_skips_archive(self):
        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = eng._generate_options(
            "product",
            {"id": "p1", "name": "Widget", "price": 100, "cost": 40},
            context={},
        )
        actions = [o["action"] for o in options]
        assert "archive_low_margin" not in actions

    def test_baseline_product_options_still_present(self):
        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        options = eng._generate_options("product", {"id": "p1"}, context={})
        actions = {o["action"] for o in options}
        assert "keep" in actions
        assert "add_similar" in actions
        assert "remove_underperformer" in actions


class TestEveryOptionHasRequiredFields:
    """The scoring path at _score_options reads profit_score,
    risk_score, action, and reason. Every Fix S option must
    have all four so scoring doesn't crash."""

    def test_all_dynamic_options_have_fields(self):
        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        # Scenario that fires every dynamic option
        options = eng._generate_options(
            "pricing",
            {"price": 50, "cost": 20, "inventory_quantity": 100},
            context={"competitor_alerts": ["alert"]},
        )
        for opt in options:
            assert "action" in opt
            assert "reason" in opt
            assert "profit_score" in opt
            assert "risk_score" in opt

        options = eng._generate_options(
            "product",
            {"id": "p1", "price": 10, "cost": 9, "image_url": ""},
            context={},
        )
        for opt in options:
            assert "action" in opt
            assert "reason" in opt
            assert "profit_score" in opt
            assert "risk_score" in opt


class TestDecideStillRunsWithDynamicOptions:
    """End-to-end: DecisionEngine.decide must still pick a
    winner when the dynamic options fire, and the winner
    must carry attribution."""

    def test_decide_selects_from_dynamic_set(self, tmp_path):
        from core.learning.action_weights import reset_action_weight_store
        reset_action_weight_store(tmp_path / "w.db")

        from core.brain.decision_engine import DecisionEngine
        eng = DecisionEngine()
        dec = eng.decide(
            "pricing",
            {"price": 50, "cost": 20, "inventory_quantity": 100},
        )
        assert dec.choice  # non-empty
        assert dec.options_considered >= 4  # baseline + dynamic options
